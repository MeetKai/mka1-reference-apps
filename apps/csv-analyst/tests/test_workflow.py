import base64
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

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
    download = httpx.Response(
        200,
        stream=httpx.ByteStream(b"x" * 2_000_001),
        request=httpx.Request("GET", "https://example.test/report"),
    )
    sdk.sandbox.download_file.return_value = download
    with pytest.raises(WorkflowError, match="exceeded 2 MB"):
        analyze(CSV, "Compare the monthly revenue.", sdk)
    assert download.is_closed
    sdk.sandbox.terminate.assert_called_once()
