# CSV analyst

Upload a CSV, ask a question, and download an HTML report with computed findings, tables, methods, and limitations. Each analysis runs in its own MKA1 sandbox.

## Run locally

You need Python 3.12+, [uv](https://docs.astral.sh/uv/getting-started/installation/), an MKA1 API key, an enabled model that can use shell tools, and sandbox capacity in your cluster.

From this directory:

```bash
uv sync --locked
cp .env.example .env
```

Edit `.env` with your API key, gateway URL, and model. The example names `openai:gpt-4.1`; choose a shell-capable model available in your organization.

```bash
uv run uvicorn app:app --host 127.0.0.1 --port 8002
```

Open <http://127.0.0.1:8002>. Stop the server with Ctrl+C. Restart after changing `.env`.

## Try it

Click **Use example data**, keep the default question, and click **Generate report**. Download the report when it finishes. The fictional dataset has 12 rows and 6 columns. Monthly revenue totals are July $61,000, August $64,950, and September $69,000. Check these totals when evaluating a model or changing the analysis instructions.

The report should identify its calculations and limitations. Human review is still required: a completed model response is not proof that every calculation or conclusion is correct.

## How it works

1. Validate the CSV as UTF-8 with 2–50 unique named columns, at least one data row, and consistent row widths.
2. Create a sandbox with the Python feature and a ten-minute lifetime, using a fresh demo end-user identity.
3. Upload the CSV through the SDK.
4. Call Responses with a shell tool attached to that sandbox. The model uses Python to analyze the file and write a report.
5. Download and sanitize the report, stripping model-supplied scripts, styles, attributes, and external resources. A fixed stylesheet makes the result readable.
6. Request sandbox termination in a `finally` block, including after a failed model call or download. If immediate cleanup fails, show that uncertainty explicitly.

The browser receives the finished report as a download. The web server does not save uploads or reports to an application database or permanent files. Uploaded files may be temporarily spooled while parsing the request and are closed after reading. Sandbox and upstream retention depend on your cluster.

## Limits and cleanup

- Maximum CSV: 1 MB, 20,000 data rows, and 50 columns.
- One concurrent analysis per server process.
- Sandbox startup wait: up to one minute; model request timeout: three minutes; at most 12 tool calls.
- HTML report: up to 2 MB before sanitization. Images and custom styling are removed.
- No packages are installed by the app. The analysis instructions ask the model to use Python's standard library and avoid network access. Enforce network restrictions in your sandbox infrastructure if required.

If the app is stopped during a run, immediate cleanup might not execute. The sandbox is created with a ten-minute lifetime as a fallback. If sandbox creation times out, its outcome may be unknown; check your cluster for `csv-demo-` sessions before retrying.

If an analysis fails, check model shell-tool support, sandbox capacity, gateway URL, and API-key permissions. A report is accepted only after the response completes and the report file downloads successfully.

## Checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

Tests simulate upstream responses and cover invalid CSVs, report sanitization, sandbox cleanup after success and failure, cleanup warnings, and rejected browser requests. The sample walkthrough is the live acceptance test.

Keep the app bound to localhost until you add authentication and quotas as described in the [repository README](../../README.md).
