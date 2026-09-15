# Implementation status

Updated: 2026-09-15. Version: 0.1.0a1 (early preview).

| Gate | State | Evidence / remaining work |
| --- | --- | --- |
| Host-neutral core | READY for bounded preview | Six tools, five operations, durable jobs and validated contracts |
| Portable correctness | READY at working revision | Contract, path, idempotency, lifecycle, tampering, recovery and setup checks; rerun for published commit |
| MCP protocol | READY at working revision | Actual stdio initialization, discovery, calls, schema resources and structured JSON fallback |
| Native MATLAB | PARTIAL | Six initial cases cover five operations on R2026a Update 5; separate TSV/theme regression passed; other versions/devices untested |
| Local file delivery | READY for observed cases | Original bytes, size and SHA-256 readback; host attachments unverified |
| Windows installation | PARTIAL | Wizard and bundle builder implemented; packaged clean-path and GUI checks pending |
| Codex model workflow | PARTIAL | Real protocol passed; model-driven native workflow pending |
| Other hosts | PARTIAL | ChatGPT Chat, local/cloud Work, Claude and WorkBuddy require independent acceptance |
| Cloud environment | PARTIAL | New repository absent from authenticated Codex picker despite All repositories access; environment not saved |
| Stable release acceptance | PARTIAL | Alpha preview only; clean-device, upgrade, owner review and broader host gates open |

The architecture document is an approved design record, not a list of shipped features. Warm sessions, shared IPC, remote authentication/service and host attachment adapters are not implemented.

## Recovery and privacy

Jobs, input snapshots, native logs and results stay in local application data. The official subprocess receives a small OS/licence environment, excluding model tokens. Diagnostics may contain local paths and scientific data; review them before sharing. Public checks use synthetic data.

Queued writes are idempotent. A coordinator disappearing after dispatch marks the outcome unknown and quarantines the executor. Reconcile the existing job before any retry. Cancellation is a request, not proof of exit. Setup recovery requires owner confirmation that the plugin-owned session stopped; it never kills unrelated MATLAB. Jobs and delivered files are retained for explicit review/removal; automatic pruning is not implemented.

## Measurements and limits

Initial synthetic jobs took about 12–26 seconds each including fresh MATLAB startup and verification on this machine. Default output schemas are roughly 2.4–4.3 KB each. These observations do not establish general performance or token savings. Actual model usage is reported only when supplied by the host.

CSV/TSV input limit: 256 MiB. Individual artifact limit: 512 MiB. Inline MCP bytes: 16 MiB; larger files use resource/local delivery. One coordinator accepts at most ten active jobs. Input/output directories must be selected in setup.
