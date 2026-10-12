# Validation

Checked on October 12, 2026 against the public MKA1 API gateway using the published Python SDK and fictional data.

| Check | Result |
| --- | --- |
| Fresh public clone without GitHub credentials | Passed |
| Independent installation with `uv sync --locked --python 3.12` | Passed for both apps |
| Python formatting and lint | Passed for both apps |
| Automated tests on Python 3.12 and 3.13 | 54 passed: 12 for ticket triage, 42 for CSV analyst |
| Browser ticket submission with `openai:gpt-4.1-mini` | Passed; dispatch outage returned technical support / P1 |
| Other three sample tickets through the running app | Passed; billing / P3, account services / P3, technical support / P2 |
| Browser example-data analysis and report download with `openai:gpt-4.1` | Passed |
| Sample report calculations | Source rows matched; all three $1,500 revenue-increase ties included; no decreases; monthly ticket totals 211, 199, 181 |
| Browser submission without a file | Rejected with instructions to choose a file |
| Browser upload with inconsistent CSV row widths | Rejected with a specific validation error |
| Valid upload after an invalid upload | Passed without restarting the app |
| Separate uploaded CSV with positive and negative changes | Report matched the expected figures below |
| Background-job browser flow | Passed; browser received the completed report through status polling |
| Empty-report fault injection with live model recovery | Passed; an injected first completion left an empty file, one live model request regenerated it, and sandbox termination was confirmed |
| Sandbox cleanup | Recent CSV test sessions were reported as terminated by the API |

The separate upload used [monthly-changes.csv](apps/csv-analyst/tests/fixtures/monthly-changes.csv) with this question:

> Compute overall revenue and support-ticket totals for each month. Show revenue changes between consecutive months, including percentage changes. State the largest increase and the largest decrease.

The downloaded report contained these values:

| Month | Revenue | Support tickets | Revenue change | Percentage change |
| --- | ---: | ---: | ---: | ---: |
| 2026-07 | 300 | 30 | Not applicable | Not applicable |
| 2026-08 | 240 | 24 | -60 | -20.00% |
| 2026-09 | 290 | 20 | +50 | +20.83% |

## Fixes from this verification

- Ticket triage now rejects decision fields containing only whitespace.
- CSV analyst now rejects reports with HTML tags but no readable body text. It preserves validated table-cell spans so grouped headers stay aligned.
- Long CSV runs now use background jobs with short browser status requests. Results expire from memory after ten minutes. Timeout messages are specific and do not expose upstream request details.
- Missing, empty, oversized, or malformed reports trigger at most one regeneration attempt in the same sandbox. Tests verify successful recovery, the two-attempt limit, and no automatic retries for authentication or service errors.
- Regression tests cover both fixes. Additional checks cover missing credentials, input limits, request-capacity recovery, sandbox startup polling and timeouts, and cleanup failures.

The suite also covers malformed model output, refusals, failed responses, invalid CSVs, cross-origin rejection, streamed downloads, report sanitization, and cleanup after failures. Tests use simulated upstream responses and do not require an API key; the browser checks above used the live API.

## Scope

An additional extended live CSV run hit an upstream read timeout, and a recovery trial encountered a connection failure that prevented immediate cleanup confirmation. A later controlled recovery trial succeeded and confirmed termination. This is an observed service limitation, not a passing test. The app reports timeouts, releases request capacity, and attempts sandbox cleanup; it does not silently repeat uncertain model requests.

These results verify the tested configuration and inputs. They do not guarantee availability of model providers or sandbox capacity, or analytical correctness on every dataset. Model output can vary; review generated reports before using them for decisions.

Both apps run locally. Hosting for other users requires the authentication, quotas, and infrastructure described in the repository README. Sandbox network restrictions must be enforced by the cluster; model instructions alone do not provide that isolation.

The FastAPI/Starlette test client emits an upstream deprecation warning about its HTTPX adapter. Tests pass. GitHub Actions is provided as a template and is not enabled in this repository.
