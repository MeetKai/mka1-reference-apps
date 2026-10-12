import base64
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient
from meetkai_mka1 import errors

import app as server
from report import sanitize_report
from workflow import WorkflowError, analyze, validate_csv

CSV = b"month,revenue\nJuly,100\nAugust,120\n"


def fake_sdk(status="completed", cleanup_error=False):
    sandbox = Mock()
    sandbox.create.return_value = SimpleNamespace(
        session=SimpleNamespace(status="running"), session_token="test_token"
    )
    sandbox.run_command.return_value = SimpleNamespace(stdout="/workspace\n")
    sandbox.download_file.return_value = httpx.Response(
        200,
        content=b"<html><body><h1>Revenue</h1><p>July: 100. August: 120.</p></body></html>",
        request=httpx.Request("GET", "https://example.test/report"),
    )
    if cleanup_error:
        sandbox.terminate.side_effect = RuntimeError("private_details")
    response = Mock(id="resp_test")
    response.model_dump.return_value = {
        "status": status,
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "Revenue increased by 20."}],
            }
        ],
    }
    return SimpleNamespace(
        sandbox=sandbox,
        llm=SimpleNamespace(responses=SimpleNamespace(create=Mock(return_value=response))),
    )


def test_csv_profile():
    assert validate_csv(CSV) == {"rows": 2, "columns": ["month", "revenue"]}
    assert validate_csv(b"\xef\xbb\xbf" + CSV)["rows"] == 2


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"a,b\n",
        b"a,A\n1,2\n",
        b"a,b\n1\n",
        b"a,b\n\xff,2\n",
        b"a,b\n\x00,2\n",
        b"a\n1\n",
        b'a,b\n"unfinished,2',
    ],
)
def test_invalid_csv_rejected(raw):
    with pytest.raises(ValueError):
        validate_csv(raw)


def test_report_sanitizer_removes_active_content_and_preserves_tables():
    result = sanitize_report("""<html><head><style>body{background:url(https://evil.test)}</style></head>
    <body onload="alert(1)"><script>fetch('secret')</script><img src="https://evil.test">
    <svg><script>alert(1)</script></svg><a href="javascript:alert(1)">Summary</a>
    <table><tr><td onclick="alert(1)">A &amp; B</td></tr></table></body></html>""").decode()
    for unwanted in [
        "https://evil",
        "javascript:",
        "onclick",
        "onload",
        "<script",
        "<img",
        "<svg",
        "fetch(",
    ]:
        assert unwanted not in result
    assert "<td>A &amp; B</td>" in result
    assert "default-src 'none'" in result


def test_analysis_uses_same_identity_and_cleans_up():
    sdk = fake_sdk()
    result = analyze(CSV, "Compare the monthly revenue.", sdk)
    assert result["cleanup_warning"] is None
    assert "Revenue increased by 20" not in result["summary"]
    assert b"July: 100" in base64.b64decode(result["report_base64"])
    sid = sdk.sandbox.create.call_args.kwargs["session_id"]
    request = sdk.llm.responses.create.call_args.kwargs
    assert request["tools"][0]["environment"]["container_id"] == sid
    assert request["x_on_behalf_of"] == sid
    assert sdk.sandbox.upload_file.call_args.kwargs["body"] == CSV
    sdk.sandbox.terminate.assert_called_once()
    assert sdk.sandbox.terminate.call_args.kwargs["session_id"] == sid


def test_failed_model_response_still_terminates_sandbox():
    sdk = fake_sdk(status="failed")
    with pytest.raises(WorkflowError, match="did not complete"):
        analyze(CSV, "Compare the monthly revenue.", sdk)
    sdk.sandbox.terminate.assert_called_once()
    sdk.sandbox.download_file.assert_not_called()


def test_failed_download_still_terminates_sandbox():
    sdk = fake_sdk()
    sdk.sandbox.download_file.side_effect = RuntimeError("download failed")
    with pytest.raises(RuntimeError):
        analyze(CSV, "Compare the monthly revenue.", sdk)
    sdk.sandbox.terminate.assert_called_once()


def test_cleanup_failure_is_visible_without_exposing_details():
    result = analyze(CSV, "Compare the monthly revenue.", fake_sdk(cleanup_error=True))
    assert "cleanup failed" in result["cleanup_warning"]
    assert "private_details" not in result["cleanup_warning"]


def test_api_rejects_invalid_input_before_upstream_call(monkeypatch):
    client = TestClient(server.app)
    run = Mock()
    monkeypatch.setattr(server, "analyze", run)
    response = client.post(
        "/api/analyze",
        data={"question": "Compare monthly revenue."},
        files={"file": ("bad.csv", b"a,b\n1", "text/csv")},
    )
    assert response.status_code == 422
    assert not run.called
    assert (
        client.post("/api/analyze", headers={"origin": "https://evil.example"}).status_code == 403
    )
    assert client.get("/", headers={"host": "evil.example"}).status_code == 400


def test_download_consumes_stream_and_closes_it():
    sdk = fake_sdk()
    stream = httpx.ByteStream(b"<html><body><p>Computed revenue: 220</p></body></html>")
    download = httpx.Response(
        200, stream=stream, request=httpx.Request("GET", "https://example.test/report")
    )
    sdk.sandbox.download_file.return_value = download
    result = analyze(CSV, "Compare the monthly revenue.", sdk)
    assert b"Computed revenue: 220" in base64.b64decode(result["report_base64"])
    assert download.is_closed


def test_oversized_stream_rejected_and_sandbox_cleaned_up():
    sdk = fake_sdk()
    downloads = [
        httpx.Response(
            200,
            stream=httpx.ByteStream(b"x" * 2_000_001),
            request=httpx.Request("GET", "https://example.test/report"),
        )
        for _ in range(2)
    ]
    sdk.sandbox.download_file.side_effect = downloads
    with pytest.raises(WorkflowError, match="exceeded 2 MB"):
        analyze(CSV, "Compare the monthly revenue.", sdk)
    assert all(download.is_closed for download in downloads)
    assert sdk.llm.responses.create.call_count == 2
    sdk.sandbox.terminate.assert_called_once()


@pytest.mark.parametrize(
    "html",
    [
        "<html><body><p> </p></body></html>",
        "<html><body><div><br></div></body></html>",
        "<html><head><title>Report</title></head><body><p>&nbsp;</p></body></html>",
    ],
)
def test_rejects_reports_without_readable_text(html):
    with pytest.raises(ValueError, match="no readable content"):
        sanitize_report(html)


def test_sandbox_startup_polling_and_failed_start_cleanup(monkeypatch):
    monkeypatch.setattr("workflow.time.sleep", lambda _: None)
    sdk = fake_sdk()
    sdk.sandbox.create.return_value.session.status = "starting"
    sdk.sandbox.get.return_value = SimpleNamespace(status="running")
    assert analyze(CSV, "Compare the monthly revenue.", sdk)["profile"]["rows"] == 2
    sdk.sandbox.get.assert_called_once()
    sdk = fake_sdk()
    sdk.sandbox.create.return_value.session.status = "failed"
    with pytest.raises(WorkflowError, match="could not start"):
        analyze(CSV, "Compare the monthly revenue.", sdk)
    sdk.sandbox.terminate.assert_called_once()
    sdk.llm.responses.create.assert_not_called()


def test_sandbox_startup_timeout_still_cleans_up(monkeypatch):
    sdk = fake_sdk()
    sdk.sandbox.create.return_value.session.status = "starting"
    clock = iter([0, 61])
    monkeypatch.setattr("workflow.time.monotonic", lambda: next(clock))
    with pytest.raises(WorkflowError, match="not ready"):
        analyze(CSV, "Compare the monthly revenue.", sdk)
    sdk.sandbox.terminate.assert_called_once()


def test_failure_and_failed_cleanup_reports_both_without_details():
    sdk = fake_sdk(status="failed", cleanup_error=True)
    with pytest.raises(WorkflowError, match="cleanup could not be confirmed") as error:
        analyze(CSV, "Compare the monthly revenue.", sdk)
    assert "private_details" not in str(error.value)


@pytest.mark.parametrize(
    "raw",
    [
        b"a,b\n" + b"1,2\n" * 20001,
        b"a,b\n" + b"x" * 1_000_000,
        (",".join(f"c{i}" for i in range(51)) + "\n" + ",".join("1" for _ in range(51))).encode(),
    ],
)
def test_csv_resource_limits(raw):
    with pytest.raises(ValueError):
        validate_csv(raw)


def test_csv_api_success_failure_recovery_and_capacity(monkeypatch):
    client = TestClient(server.app)
    run = Mock(side_effect=RuntimeError("secret_api_key"))
    monkeypatch.setattr(server, "analyze", run)

    def post():
        return client.post(
            "/api/analyze",
            data={"question": "Compare monthly revenue."},
            files={"file": ("data.csv", CSV, "text/csv")},
        )

    failed = post()
    assert failed.status_code == 202
    outcome = client.get("/api/jobs/" + failed.json()["job_id"])
    assert outcome.json()["status"] == "failed"
    assert "secret_api_key" not in outcome.text
    run.side_effect = None
    run.return_value = {"summary": "Report ready", "profile": {"rows": 2}}
    assert post().status_code == 202
    assert server.capacity.acquire(blocking=False)
    try:
        assert post().status_code == 429
    finally:
        server.capacity.release()
    assert post().status_code == 202


def test_missing_api_key_does_not_start_analysis(monkeypatch):
    monkeypatch.delenv("MKA1_API_KEY", raising=False)
    with pytest.raises(WorkflowError, match="Set MKA1_API_KEY"):
        analyze(CSV, "Compare monthly revenue.")


@pytest.mark.parametrize("body", [b"", b"not HTML", b"<html><p> </p></html>", b"<html>\xff</html>"])
def test_invalid_report_is_regenerated_once_in_same_sandbox(body):
    sdk = fake_sdk()
    valid = sdk.sandbox.download_file.return_value
    invalid = httpx.Response(
        200, content=body, request=httpx.Request("GET", "https://example.test/report")
    )
    sdk.sandbox.download_file.side_effect = [invalid, valid]
    result = analyze(CSV, "Compare the monthly revenue.", sdk)
    assert b"July: 100" in base64.b64decode(result["report_base64"])
    assert sdk.llm.responses.create.call_count == 2
    assert (
        "previous attempt failed validation" in sdk.llm.responses.create.call_args.kwargs["input"]
    )
    sdk.sandbox.create.assert_called_once()
    sdk.sandbox.terminate.assert_called_once()
    assert invalid.is_closed and valid.is_closed


def test_recovery_stops_after_second_empty_report_and_cleans_up():
    sdk = fake_sdk()
    sdk.sandbox.download_file.side_effect = [
        httpx.Response(
            200, content=b"", request=httpx.Request("GET", "https://example.test/report")
        )
        for _ in range(2)
    ]
    with pytest.raises(WorkflowError, match="after two attempts"):
        analyze(CSV, "Compare the monthly revenue.", sdk)
    assert sdk.llm.responses.create.call_count == 2
    sdk.sandbox.create.assert_called_once()
    sdk.sandbox.terminate.assert_called_once()


@pytest.mark.parametrize("status", [404, 403, 503])
def test_missing_file_recovers_but_auth_and_service_errors_do_not_retry(status):
    sdk = fake_sdk()
    response = httpx.Response(
        status, text="upstream details", request=httpx.Request("GET", "https://example.test/report")
    )
    error = errors.SDKDefaultError("API error", response, response.text)
    sdk.sandbox.download_file.side_effect = [error, sdk.sandbox.download_file.return_value]
    if status == 404:
        assert analyze(CSV, "Compare the monthly revenue.", sdk)["cleanup_warning"] is None
        assert sdk.llm.responses.create.call_count == 2
    else:
        with pytest.raises(errors.SDKDefaultError):
            analyze(CSV, "Compare the monthly revenue.", sdk)
        assert sdk.llm.responses.create.call_count == 1
    sdk.sandbox.terminate.assert_called_once()


def test_background_job_result_polling_and_expiration(monkeypatch):
    client = TestClient(server.app)
    result = {"report_base64": "aGVsbG8=", "profile": {"rows": 2}}
    monkeypatch.setattr(server, "analyze", Mock(return_value=result))
    response = client.post(
        "/api/analyze",
        data={"question": "Compare monthly revenue."},
        files={"file": ("data.csv", CSV, "text/csv")},
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    completed = client.get("/api/jobs/" + job_id).json()
    assert completed == {"status": "completed", "result": result}
    server.expire_job(job_id)
    assert client.get("/api/jobs/" + job_id).status_code == 404


def test_background_timeout_is_actionable_and_capacity_is_released(monkeypatch):
    client = TestClient(server.app)
    monkeypatch.setattr(
        server, "analyze", Mock(side_effect=httpx.ReadTimeout("private upstream URL"))
    )
    response = client.post(
        "/api/analyze",
        data={"question": "Compare monthly revenue."},
        files={"file": ("data.csv", CSV, "text/csv")},
    )
    outcome = client.get("/api/jobs/" + response.json()["job_id"])
    assert outcome.json()["status"] == "failed"
    assert "timed out" in outcome.json()["error"]
    assert "private upstream" not in outcome.text
    assert server.capacity.acquire(blocking=False)
    server.capacity.release()


def test_timeout_still_terminates_sandbox_without_repeating_model_call():
    sdk = fake_sdk()
    sdk.llm.responses.create.side_effect = httpx.ReadTimeout("upstream timeout")
    with pytest.raises(httpx.ReadTimeout):
        analyze(CSV, "Compare monthly revenue.", sdk)
    sdk.llm.responses.create.assert_called_once()
    sdk.sandbox.terminate.assert_called_once()


@pytest.mark.parametrize(
    "attrs,expected",
    [
        ('colspan="2" rowspan="3" onclick="alert(1)"', '<th colspan="2" rowspan="3">'),
        ('colspan="9999" rowspan="0" style="color:red"', "<th>"),
        ('colspan="2 onmouseover=alert(1)"', "<th>"),
    ],
)
def test_sanitized_table_headers_preserve_only_valid_spans(attrs, expected):
    report = sanitize_report(
        f"<html><table><tr><th {attrs}>North</th></tr></table></html>"
    ).decode()
    assert expected + "North</th>" in report
    assert "onclick" not in report and "onmouseover" not in report
