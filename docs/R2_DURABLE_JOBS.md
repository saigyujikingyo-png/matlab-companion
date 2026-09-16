# R2: client-independent installed jobs

Owner authorization and release: 2026-09-16. R2 is implemented and published as a scoped Windows preview.
Baseline: alpha.2 runtime `41f9cf7`, documentation `cbe6bd9`.

## Immutable release identity

Runtime/source: `1b2eb73bcd674056cf756260ee5359c083c24afe`.
Version: `0.1.0a3` / release `v0.1.0-alpha.3`.
Windows ZIP: 33,104,323 bytes; SHA-256
`d6a839606570d94a83407b7d1276bd2068c72c260d03cda210f33c7841b30aaa`.
This identifies the published archive. Package, native, installed-host, model
and publication receipts retain their separate scopes. Saved cloud-container
acceptance remains unverified; build identity alone does not close a gate.

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
| Private IPC ownership and framing | Implemented; Windows framing, deadline and explicit ACL tests passed; final Ubuntu CI passed the applicable POSIX checks |
| Real two-client/disconnect behavior | Portable prestarted coordinator with two SDK clients passed; strict host automatic-start refusal passed separately |
| Exact-source portable suite | [CI 35083094659](https://github.com/saigyujikingyo-png/matlab-companion/actions/runs/35083094659) at `1b2eb73`: Windows 364 passed, 6 skipped; Ubuntu 363 passed, 7 skipped. Both passed Ruff, 22 schemas, actual stdio and public audit |
| Earlier source-native lifecycle | Historical pass at `de1cf61`: disconnect, explicit cancellation and crash/quarantine, each with separate session/sentinel observations; see the retained checkpoint below |
| Relocated final package | [Passed](../verification/package-v0.1.0-alpha.3.json): 3,991 manifest entries, zero mismatches/unlisted files, pre/post-runtime hash readback, Python 3.12.14, isolated self-test, stdio and withdrawn Tk; zero jobs/dispatches and independent prestarted-coordinator idle exit. Focused builder-path scan had zero matches |
| Exact-package native lifecycle | [Passed three cases](../verification/native-r2-v0.1.0-alpha.3.json): disconnect, explicit cancellation and crash/quarantine. One native entry per case; synthetic sentinel preserved. Crash exit was independently observed while production exit observation remained unconfirmed |
| Exact-package native science / local delivery | [Passed six cases](../verification/native-v0.1.0-alpha.3.json) covering five operations, 43 original-file readbacks and six held-handle-confirmed native exits on R2026a Update 5 |
| Representative Codex model and seven-file delivery | [Passed after correction](../verification/codex-r2-v0.1.0-alpha.3.json): three actual turns, 14 MCP calls, one scientific job/dispatch, three valid waits and seven verified originals. First-attempt success false; one delivery omitted `job_id`. Requested Terra max; resolved metadata unavailable |
| Current-device upgrade / registered host | [Passed for recorded scope](../verification/local-upgrade-v0.1.0-alpha.3.json): runtime, official connection, enabled plugin cache, selected-root shortcut and backups verified; settings/jobs, alpha.2 files and seven other connections preserved. Six validated schemas/calls and ten resource reads used the registered command; no coordinator/native execution |
| Saved cloud development container | Unverified for alpha.3; successful Ubuntu CI is separate. This broader combination is outside the accepted preview scope |
| Release publication | [Passed](../verification/release-v0.1.0-alpha.3.json): exact runtime tag, GitHub asset digest and fresh ZIP/checksum readback match the archive above; alpha.2 is retained for rollback |

Scientific originals and unknown-job evidence have no automatic expiry. Idle
exit must not delete jobs or equate a backend return with native process exit.
Storage observations describe the measured scope and any scan limit; they are
not promises of disk quota enforcement or complete cleanup.

## Final-package native scope

Both final native receipts bind the relocated package interpreter and imported
runtime hashes to the immutable manifest. Their live-checkout `source_dirty`
field reflects post-build documentation/evidence edits; `package_source_dirty`
is false. The package runtime was not replaced by source-checkout imports.

In the crash case, the production observer was interrupted before confirming a
response or native exit. A separate held process handle later observed exit,
but the job remained unknown, no late receipt was observed, quarantine remained,
and new dispatch was refused. This is a successful preservation check, not
successful scientific completion. Disconnect and cancellation separately
confirmed production exit observations. The prestarted route and synthetic
sentinel do not establish startup under every host or preserve an arbitrary
user-owned MATLAB session by inference.

The [first model preparation attempt](../verification/codex-r2-first-preparation.json)
stopped before Codex invocation, with zero jobs/dispatches, because an ignored
operator compared resolved and unresolved Windows paths. An empty ready
coordinator was independently observed. Correcting only the operator's private
root normalization did not alter the package or replay work.

The [first actual model attempt](../verification/codex-r2-first-model-attempt.json)
stopped before any Companion call, job or dispatch: the ignored operator had
disabled the required code-mode host. Removing that override did not change the
runtime. The second actual turn completed the 41-point kinetics job and three
valid waits but omitted `job_id` from its first delivery request. That rejected
call copied no bytes. The third turn performed only delivery from the same
completed job; seven originals passed independent hash/readback checks and
protected job records were unchanged. No additional scientific job or dispatch
was created. All three turns remain in the combined receipt: 191.688 seconds,
277,722 input (213,504 cached), 7,236 output (4,301 reasoning) tokens.
First-attempt success is false; resolved model/effort metadata is unknown, and
no cost or quota saving is inferred. The usability failure does not authorize
starting the separately proposed R3 increment.

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

The Windows GitHub runner rejected both nested clients' independent-process
creation with WinError 5 in [CI 35082324331](https://github.com/saigyujikingyo-png/matlab-companion/actions/runs/35082324331).
Both returned `COORDINATOR_START_BLOCKED`, made exactly one launch attempt and
created no service or job store. The positive two-client automatic-start check
is skipped only for that fully observed restriction; other startup errors still
fail. Local Windows and Ubuntu positive evidence and the explicit restrictive
Windows Job refusal test remain separate. No ordinary-child fallback or host
restriction workaround is introduced.

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
