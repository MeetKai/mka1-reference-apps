# Cryptography inventory

This repository contains two local reference applications (`apps/ticket-triage`, `apps/csv-analyst`). They implement no cryptographic primitives, protocols, certificate handling, key management, password hashing, signing, or token generation. They do not offer encryption, signing, or key handling to users. No configuration value selects an algorithm, key size, curve, hash, TLS version, or cipher suite.

## Security-relevant uses

| Where | What | Algorithm / library | Notes |
| --- | --- | --- | --- |
| `apps/*/workflow.py` (`SDK(server_url=...)`) | TLS client connection to the MKA1 API | TLS with library defaults, via `meetkai-mka1` → `httpx` → Python `ssl` + `certifi` CA bundle | Certificate verification is on; nothing in this repository disables or configures it. `MKA1_SERVER_URL` selects the endpoint only. |
| `apps/*/.env` (`MKA1_API_KEY`) | Bearer credential sent to the API | None generated here | Supplied by the operator; read from the environment and sent in the `Authorization` header by the SDK. Never written to disk or logs by the apps. |
| `apps/csv-analyst/workflow.py` (`session_token`) | Sandbox session token | None generated here | Issued by the MKA1 API when a sandbox session is created and passed back unchanged on later calls. |

## Non-security uses (identifiers only)

| Where | What | Library |
| --- | --- | --- |
| `apps/ticket-triage/workflow.py:81` | `X-On-Behalf-Of` demo identity (`triage-demo-<uuid4>`) | `uuid.uuid4()` |
| `apps/csv-analyst/workflow.py:119` | `X-On-Behalf-Of` demo identity (`csv-demo-<uuid4>`) | `uuid.uuid4()` |
| `apps/csv-analyst/app.py:130` | In-process job id | `uuid.uuid4()` |

## Dependencies that perform cryptography

From `apps/*/uv.lock`: `httpx` (TLS via `ssl`), `certifi` (CA bundle), `anyio`/`h11`/`idna` (transport, no crypto of their own). No `cryptography`, JWT, bcrypt/argon2, NaCl, or other crypto packages are present.

## Keeping this current

Any new use of `hashlib`, `hmac`, `secrets`, `ssl`, `cryptography`, JWT libraries, or TLS settings must be added to this file. Do not add algorithm-selecting configuration.
