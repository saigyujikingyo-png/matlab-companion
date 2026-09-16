# R2: client-independent installed jobs

Owner authorization: 2026-09-16. Implementation and acceptance are in progress.
Baseline: alpha.2 runtime `41f9cf7`, documentation `cbe6bd9`.

## Change contract

One on-demand process owns the existing Core and file store for each user and
resolved installation root. Thin stdio front ends connect through private local
JSON IPC. They do not own scientific workers. Closing a client abandons its
response, while an explicit `matlab_job` cancellation changes durable intent.

Keep the six tools, five scientific operations, pinned dependencies, original
artifacts, nested job envelope, idempotency and R1 quarantine semantics. R3
delivery and unit-edit changes remain outside this increment. Do not introduce
a public network listener, database, always-on service or new MATLAB termination.

## Integration order

1. Add owner-scoped local transport and isolated process ownership.
2. Integrate the coordinator and thin stdio front end; verify two-client access
   and survival of a real client disconnect before extending the surface.
3. Add factual job phases, durable monotonic event numbers and bounded waiting;
   keep legacy state files readable without diagnostic migration writes.
4. Exercise crashes, cancellation, queue limits, idle exit, configuration
   differences and accounting/retention. Review the integrated implementation.
5. Verify native lifecycle, exact package, installed operation and applicable
   host/model/cloud evidence separately; publish only the scopes demonstrated.

## Ownership and transport

The coordinator holds an OS-released lock for its lifetime. Its private record
binds an instance UUID, process creation identity, runtime and configuration to
the endpoint. Another runtime/configuration cannot silently take over a live
coordinator. Lost RPC responses never cause automatic write retries.

Windows uses a named pipe with an explicit current-user ACL and remote clients
rejected. POSIX uses an owner-only Unix socket directory. Frames are bounded JSON,
never pickle. The private command allowlist is separate from public tools.

Detached console flags do not establish independent Windows process lifetime.
The launcher must use supported breakaway behavior and fail clearly if the host
job disallows it. No task scheduler, parent spoofing or broker workaround is used
to evade that boundary. Acceptance must distinguish strict host jobs from a
coordinator independently started by the user through a supported entrypoint.

## Evidence ledger

| Gate | Current result |
| --- | --- |
| Unmodified alpha.2 portable baseline | 215 tests passed locally on 2026-09-16 |
| Private IPC ownership and framing | Implemented; Windows framing, deadline and explicit ACL tests passed; POSIX checks await Linux CI |
| Real two-client/disconnect behavior | Portable prestarted coordinator with two SDK clients passed; strict host automatic-start refusal passed separately |
| Durable wait/progress and restart semantics | Integrated Windows suite: 362 passed, 5 platform skips; Ruff, 22 schemas, actual stdio and public audit passed on 2026-09-16 |
| Native lifecycle and session accounting | Pending independent acceptance |
| Package, installed host and release | Pending exact candidate |

Scientific originals and unknown-job evidence have no automatic expiry. Idle
exit must not delete jobs or equate a backend return with native process exit.
Storage observations describe the measured scope and any scan limit; they are
not promises of disk quota enforcement or complete cleanup.

## Preserved first-candidate findings

Candidate `e99a5cd` passed its local Windows suite. Its first Linux CI run
identified a service child that had exited but was not reaped by a still-running
frontend. A daemon waiter now reaps only that exact child after exit; it never
signals the service or keeps a disconnected frontend alive. CI platform jobs
now finish independently so a Linux failure does not cancel Windows evidence.

The [first native probe](../verification/native-r2-first-probe.json) stopped
before any Companion job was submitted: a second-generation base-Python harness
child lost its controller's dependency roots and could not import MCP. Zero
Companion jobs or dispatches were observed. The synthetic sentinel retained its
state, acknowledged cooperative shutdown and independently exited. The corrected
harness propagates the original runtime/dependency binding and checks two real
Python child generations without MATLAB. This failed probe is not native R2
acceptance and no unknown scientific write was replayed.

At `de1cf61`, the [corrected source-native checkpoint](../verification/native-r2-source-checkpoint.json)
passed all three lifecycle cases. Disconnect and cancellation each completed with
one native entry and separately verified exit. Crash recovery retained unknown
state and quarantine, refused new dispatch and exited idle-degraded; no late
receipt arrived. An independent held handle observed that crash-case native exit,
while the interrupted production observer correctly retained an unconfirmed exit.
The synthetic sentinel preserved its state and cooperatively exited.

Subsequent integrated testing exposed a Windows CRT file-open race reported as
`errno=13` without `winerror`. The existing bounded 250 ms file-sharing retry now
also handles this Windows-only form. Its regression failed before the fix and
passed afterward; permanent access denial still ends within the same bound.
Only file I/O is retried, never native execution. This source checkpoint and its
package audit remain separate from the final rebuilt archive's acceptance.

The default idle window is 30 seconds; an explicit Setup **Start job service**
uses 300 seconds to allow the user to return to their host. Individual client
disconnect never cancels accepted work. Closing the entire host or outer Windows
Job is outside this guarantee. `wait.timeout_seconds` (0–10, default 5) measures
the accepted Core wait, separately from startup, connection and filesystem I/O.

Windows launch and lifetime choices were checked against Microsoft's
[process creation flags](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags)
and [Job objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
on 2026-09-16. A remaining outer Job membership is not proof of membership in an
individual frontend's Job. The coordinator records the observable Job limits;
actual disconnect acceptance supplies the bounded lifetime evidence.
