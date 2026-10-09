# Validation

Validated on October 9, 2026 against the public MKA1 API gateway using the published Python SDK and fictional sample data.

| Check | Result |
| --- | --- |
| Independent dependency installation with `uv sync --locked` | Passed for both apps |
| Python formatting and lint | Passed for both apps |
| Automated tests without API credentials | 26 passed |
| Browser ticket submission with `openai:gpt-4.1-mini` | Passed |
| All four sample tickets' expected team and priority | Passed |
| Browser CSV upload, sandbox analysis, report download, and cleanup request with `openai:gpt-4.1` | Passed |
| Review of sample report figures | Matched source rows; largest increase of $1,500 correctly included all three ties; no decreases; monthly ticket totals 211, 199, 181 |

Model output can vary. These checks establish the sample's observed behavior, not a guarantee of analytical correctness on other data. Review generated reports before using them for decisions.

The CSV app strips active HTML and external resources from downloaded reports. Model instructions to avoid network access are not enforced by the app; use your cluster's sandbox controls for isolation requirements.

The automated suite includes invalid model output, refusal and failed-response handling, malformed CSVs, cross-origin rejection, streaming report downloads, report sanitization, and sandbox cleanup on failure. The current FastAPI/Starlette test client emits an upstream deprecation warning about its HTTPX adapter; tests still pass.
