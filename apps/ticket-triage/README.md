# Ticket triage

Paste a telecom support ticket or select a fictional example. The app returns a suggested team, priority, summary, rationale, and next action for a human reviewer. It does not submit tickets, change accounts, or send messages.

## Run locally

You need Python 3.12+, [uv](https://docs.astral.sh/uv/getting-started/installation/), and an MKA1 API key with access to a model that supports structured output.

From this directory:

```bash
uv sync --locked
cp .env.example .env
```

Edit `.env`. Set `MKA1_API_KEY` to your API key and `MKA1_SERVER_URL` to your cluster's gateway. Set `MKA1_MODEL` to an enabled structured-output model. The example names `openai:gpt-4.1-mini`; availability depends on your organization.

```bash
uv run uvicorn app:app --host 127.0.0.1 --port 8001
```

Open <http://127.0.0.1:8001>. Stop the server with Ctrl+C. Run from this directory so dependencies and configuration resolve consistently.

## Try it

Choose **Business connectivity outage**, then submit the ticket. Expect `technical_support` and `P1`, with a suggested investigation or escalation. The other examples cover billing, plan changes, and a single-customer outage. Expected labels are recorded in `samples.json`; wording may vary between model runs.

The app rejects incomplete responses, refusals, invalid JSON, unknown team or priority values, and extra output fields. It never repairs an invalid decision into a success. If a model ignores the schema, choose another structured-output model.

## How it works

1. The browser sends the ticket to the local Python server.
2. The server calls `sdk.llm.responses.create` with an explicit routing policy, a JSON schema, and a fresh demo end-user identity.
3. Pydantic validates the returned decision before the interface displays it.

Edit `POLICY` and `Decision` in `workflow.py` together to adapt routing rules. The allowed teams are billing, technical support, and account services. P1 means a stated widespread or business-critical outage; P2 means unusable service or an urgent billing/access problem; P3 means a routine question or change.

## Checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

Tests simulate model responses and verify rejected results, input validation, cross-origin rejection, and redaction of upstream error details. The manual sample test above exercises the real API.

## Limits

Tickets are limited to 12,000 characters and two concurrent requests. Model calls have a 90-second timeout. API errors show a safe message; server logs record only the exception class. The app keeps no ticket database. Restart after changing `.env`.

Keep this app bound to localhost until you add authentication and quotas as described in the [repository README](../../README.md).
