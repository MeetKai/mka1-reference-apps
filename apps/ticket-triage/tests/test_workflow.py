import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

import app as server
from workflow import WorkflowError, classify

DECISION = {
    "team": "technical_support",
    "priority": "P1",
    "summary": "Dispatch outage",
    "rationale": "All dispatch lines are unavailable.",
    "next_action": "Escalate for review.",
}


def fake_sdk(text=None, status="completed", content=None):
    response = Mock(id="resp_test")
    response.model_dump.return_value = {
        "status": status,
        "output": [
            {
                "type": "message",
                "content": content
                or [
                    {
                        "type": "output_text",
                        "text": text if text is not None else json.dumps(DECISION),
                    }
                ],
            }
        ],
    }
    create = Mock(return_value=response)
    return SimpleNamespace(llm=SimpleNamespace(responses=SimpleNamespace(create=create)))


def test_validates_decision_and_requests_strict_schema():
    sdk = fake_sdk()
    assert classify("Dispatch lines unavailable", sdk)["decision"] == DECISION
    args = sdk.llm.responses.create.call_args.kwargs
    assert args["text"]["format"]["strict"] is True
    assert args["store"] is False
    assert args["x_on_behalf_of"].startswith("triage-demo-")


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        '{"team":"unknown"}',
        json.dumps({**DECISION, "priority": "P0"}),
        json.dumps({**DECISION, "extra": "field"}),
    ],
)
def test_rejects_malformed_or_out_of_policy_results(text):
    with pytest.raises(WorkflowError, match="invalid routing decision"):
        classify("Dispatch lines unavailable", fake_sdk(text))


def test_rejects_failed_response_even_with_valid_json():
    with pytest.raises(WorkflowError, match="did not complete"):
        classify("Dispatch lines unavailable", fake_sdk(status="failed"))


def test_rejects_refusal():
    with pytest.raises(WorkflowError, match="refused"):
        classify("Dispatch lines unavailable", fake_sdk(content=[{"type": "refusal"}]))


def test_api_validation_errors_and_credential_redaction(monkeypatch):
    client = TestClient(server.app)
    classify_mock = Mock(side_effect=RuntimeError("secret_api_key"))
    monkeypatch.setattr(server, "classify", classify_mock)
    assert client.post("/api/triage", json={"ticket": " " * 20}).status_code == 422
    assert not classify_mock.called
    response = client.post("/api/triage", json={"ticket": "My network stopped working."})
    assert response.status_code == 502
    assert "secret_api_key" not in response.text
    classify_mock.side_effect = None
    classify_mock.return_value = {"decision": DECISION, "response_id": "test"}
    assert (
        client.post("/api/triage", json={"ticket": "My network stopped working."}).status_code
        == 200
    )


def test_cross_site_requests_and_unknown_hosts_are_rejected():
    client = TestClient(server.app)
    assert (
        client.post(
            "/api/triage",
            headers={"origin": "https://evil.example"},
            json={"ticket": "My network stopped working."},
        ).status_code
        == 403
    )
    assert client.get("/", headers={"host": "evil.example"}).status_code == 400
    assert "default-src 'self'" in client.get("/").headers["content-security-policy"]
