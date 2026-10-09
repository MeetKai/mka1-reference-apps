# MKA1 reference apps

Runnable applications built with the MKA1 API and its published Python SDK. Each app has a browser interface, fictional sample data, its own dependencies, and setup instructions. Clone this repository and run either app independently.

| Application | What you can do | API features |
| --- | --- | --- |
| [Ticket triage](apps/ticket-triage/) | Turn a customer-support ticket into a team, priority, rationale, and suggested next action | Responses and structured output |
| [CSV analyst](apps/csv-analyst/) | Upload a CSV, ask a question, and download an HTML analysis report | Responses, shell tools, and sandbox file operations |

## Start an app

Install Python 3.12 or later and [uv](https://docs.astral.sh/uv/getting-started/installation/). Get an API key and a model enabled in your MKA1 organization. CSV analyst also requires sandbox capacity.

```bash
cd apps/ticket-triage
uv sync --locked
cp .env.example .env
```

Edit `.env` to set your API key, gateway URL, and model. Then run:

```bash
uv run uvicorn app:app --host 127.0.0.1 --port 8001
```

Open <http://127.0.0.1:8001>. For CSV analysis, follow [its setup instructions](apps/csv-analyst/README.md) and use port 8002.

These apps call the real API. Requests use your organization's model and sandbox resources. Start with the included fictional data. API keys stay in the Python server; the browser does not receive them. Each request uses a separate demo end-user identity in `X-On-Behalf-Of`.

## How the code is organized

Each app is self-contained:

- `app.py` serves the browser interface, validates requests, and handles errors.
- `workflow.py` calls the SDK and validates the result.
- `static/` contains the interface without a frontend build step.
- `tests/` covers validation, failure handling, and the API boundary with simulated upstream responses.
- `uv.lock` fixes dependency versions for reproducible installation.

There is no shared application package or dependency on a local SDK checkout. You can copy an app directory into a separate repository.

## Run the checks

Run these commands inside each app directory:

```bash
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

Automated tests use no credentials and make no model calls. The per-app README includes a manual acceptance test against a live cluster.

The [GitHub Actions template](ci/github-actions.yml) runs these checks for both apps. To enable it, a maintainer with workflow permissions can move it to `.github/workflows/checks.yml`.

## Before hosting for other users

These are local reference applications. They bind to localhost and reject cross-origin browser submissions. To host one, add application authentication, map authenticated users to authorized end-user identities, enforce per-user quotas, and configure your reverse proxy and allowed hosts. Keep API keys server-side. For CSV analysis, enforce any required network and filesystem restrictions through your sandbox infrastructure; model instructions are not an isolation boundary.

`store=False` disables response storage requested by these apps. It does not establish an organization-wide data retention policy or control provider logging. Review your cluster's configuration before uploading customer data.

See the [MKA1 API documentation](https://docs.mka1.com) for API keys, model access, and sandbox configuration.

## License

[Apache License 2.0](LICENSE).
