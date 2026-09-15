# R1 reliability implementation

Date: 2026-09-15. Owner approved R1 after the alpha review. Runtime version:
**0.1.0a2**. R2/R3 are not part of this increment.

## Changed behavior

| Requirement | Implementation | Current evidence |
| --- | --- | --- |
| Passive diagnostics | CLI status/self-test and setup use validated observations without creating Core, workers, queues or a missing root | Real CLI subprocesses and queued/dispatched byte-preservation tests; both missing and configured roots |
| One selected root | CLI, GUI, settings and OfficialBackend use the same resolved installation root | Two deliberately different installations/backend paths, unset default and environment-override cases |
| Durable execution isolation | Terminal or quarantined outcome is recorded under the execution lock; a pre-dispatch active marker blocks after crash or persistence failure | Controlled two-coordinator interleave, actual child-process exit, failed quarantine persistence and malformed receipt regressions |
| Owner identity | Coordinator instance UUID plus OS creation identity; native session UUID/PID is separately observed before scientific execution | Live child-process identity tests, simulated reused PID and the bounded native lifecycle receipt below |
| Late receipt | A validated terminal result cannot be downgraded by the timeout worker's stale unknown transition | Controlled reconciliation between timeout observation and state write |
| Concurrent persistence | Each atomic JSON write exclusively creates a unique temporary file; a committed immutable manifest can complete after a transient later write failure | Deterministic same-process two-writer interleave and post-manifest failure/reconcile regressions, with unchanged original hashes and one backend invocation |
| Usable large-file route | Over 16 MiB read returns existing not_delivered/local_copy metadata and instructions; no ResourceLink to an unreadable resource | Exact limit minus/equal/plus one tests, real MCP stdio read-to-deliver, original size/hash readback and invalid-producer rejection |
| Recovery UI | Matching active/quarantine markers are preserved in a recovery receipt and retired only after the existing stop confirmation, locks and exact marker checks | Matching, mismatched, corrupt, changed and newly appearing active-marker regressions |

Six public tools, five scientific operations, existing result fields and pinned
dependencies remain. The lockfile changes only the product version. Scientific
recipes are unchanged. New `native-session.json` is private execution evidence,
not a public scientific artifact or a native-stop certificate.

## Execution and recovery semantics

Ordinary service construction remains the explicit recovery boundary: a fully
registered, undispatched orphan queue can resume using its original idempotency
intent. Diagnostics never construct that service. A dispatched request is never
replayed by recovery, retries, status or reconciliation.

Before native dispatch, the executor commits `executor-active.json`, then the
job's immutable dispatch identity. It retains the OS execution lock through
receipt validation and terminal/quarantine publication. A crash or failed write
may leave the active marker. The next lock owner must quarantine that prior job
before dispatching any new one. This also protects a coordinator that was already
open before the crash, rather than relying only on startup recovery.

A late valid receipt can establish completed, failed or cancelled computation;
it does not remove quarantine automatically. Setup requires separate confirmation
that the matching native session stopped. No new MATLAB termination behavior is
introduced. The independent native acceptance uses held OS handles for exit
observations and an unrelated, explicitly owned synthetic sentinel session.

Windows creation identity uses
[GetProcessTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes).
An existing process handle remains valid after exit, so identity and liveness
are deliberately separate observations. Linux uses boot identity plus process
start ticks. Missing/legacy/inaccessible creation identity remains conservative;
it cannot prove an owner exited. MATLAB's documented
[matlabProcessID](https://www.mathworks.com/help/matlab/ref/matlabprocessid.html)
is guarded for releases without that API; unavailable PID is JSON null.

## Verification ledger

- **Portable integration: READY on the development device.** `uv run pytest -q`
  passed 215 tests after independent review exposed and reproduced two additional
  persistence failures. Ruff, 22 schema checks, real stdio smoke and public source
  audit passed. The diagnostic, resource-limit and isolation defects were
  reproduced before their repairs. These tests use synthetic backend doubles
  where identified and do not claim native science.
- **Exact runtime CI: READY.** [CI receipt](../verification/ci-v0.1.0-alpha.2.json)
  binds `41f9cf7` to Windows 215 passed and Ubuntu 214 passed/one Windows-only skip,
  plus lint, schemas, stdio and source audit.
- **Native R1 lifecycle: READY for the recorded fault case.**
  [Receipt](../verification/native-r1-lifecycle.json): normal profile completed;
  injected coordinator response loss produced unknown/quarantine, blocked a new
  dispatch and preserved one execution. A genuine late cancellation receipt was
  reconciled. A separate owned MATLAB sentinel retained identity/state across
  315 observations; held OS handles confirmed all test sessions eventually
  exited. This does not claim upstream RPC cancellation or general termination.
- **First probe failure retained.** The [first probe](../verification/native-r1-first-probe.json)
  stopped its Python worker after a transient heartbeat read failure; it did not
  reach the intended interruption case. The harness now performs bounded read
  retries within the original deadline. [Existing-job recovery](../verification/native-r1-prior-recovery.json)
  retained that original write as unknown, with zero backend executions and
  unchanged original bytes. It was not replayed or counted as a scientific pass.
- **Final package and science: READY for recorded cases.**
  [Package audit](../verification/package-v0.1.0-alpha.2.json): clean `41f9cf7`,
  33,054,016-byte archive, 3,976 manifest files, no mismatch or unlisted files,
  relocated protocol and hidden Tk pass. [Native package receipt](../verification/native-v0.1.0-alpha.2.json)
  records six cases/all five operations, 43 locally delivered original files,
  applicable numerical/native reopen/script checks and 136.844 seconds total.
  SHA-256: `7f34fa35efc5969cf1e2aa6b72e573a05c1ce8c5a5e6ac93a77dfc9f0754f3c4`.
  The alpha.1 archive remains the rollback artifact.
- **Publication: READY.** The [GitHub prerelease](https://github.com/saigyujikingyo-png/matlab-companion/releases/tag/v0.1.0-alpha.2)
  retains that exact archive; its asset digest and a fresh ZIP/checksum download
  match ([publication receipt](../verification/release-v0.1.0-alpha.2.json)).
- **Current-device upgrade: READY for recorded scope.** The
  [upgrade receipt](../verification/local-upgrade-v0.1.0-alpha.2.json) records the
  alpha.1 to alpha.2 transition through packaged setup and the official Codex
  CLI. Settings, jobs, alpha.1 files and pre-existing other MCP entries were
  preserved. The enabled plugin cache and Start-menu target were refreshed;
  the registered runtime passed passive self-test and read-only MCP checks.
  Prior connection/plugin/shortcut backups remain private. This operator-led
  upgrade does not establish an automatic updater or downgrade/removal support.
- **Model, GUI and cloud-container acceptance:** historical alpha.1 evidence
  keeps its original identity. No new installed model, visible wizard, fresh
  device, additional host or saved cloud-container pass is inferred from R1 tests.

## Remaining work

Client-independent job lifetime, bounded wait/progress, staged atomic delivery,
unit-aware label editing, matched full model benchmarking and broader visible or
new-device installation/upgrade/removal remain R2/R3 proposals. Warm sessions, new scientific
operations, remote transport and new hosts are outside this increment.
