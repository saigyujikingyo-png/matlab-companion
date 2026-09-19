# MATLAB Companion runtime lifecycle

Observed: 2026-09-19. Shared baseline: **2026-09-19.1**; lifecycle contract: **1.0**.
Status: **documentation adopted; runtime conformance remains partial**.

Accountable owner: one MATLAB Companion Product Max, with Governance High reviewing
shared contracts and incidents. Ownership transfer was verified on 2026-09-19;
private task identities and handoff records remain outside public source.
Bounded contributors work under that owner. The Terra max end-user benchmark is
a separate acceptance policy.

## Scope and immutable identities

Product: [matlab-companion](https://github.com/saigyujikingyo-png/matlab-companion),
branch codex/initial-preview. This review inspected source HEAD
f071db33bcfeb92fe4ae41d1445f7f88ee1f7c4e. Its changes after runtime commit
1b2eb73bcd674056cf756260ee5359c083c24afe are documentation and receipts only.
This adoption changes documentation, not the six-tool interface, scientific
operations, installed runtime, package version or original acceptance records.

The published Windows preview is 0.1.0a3 / v0.1.0-alpha.3. Its ZIP is
33,104,323 bytes, SHA-256
d6a839606570d94a83407b7d1276bd2068c72c260d03cda210f33c7841b30aaa.
Alpha.2 remains the retained rollback release. See [status](STATUS.md) and
[the publication receipt](../verification/release-v0.1.0-alpha.3.json).
Rule adoption does not retroactively certify this package against the new contract.

## Components and ownership

| Component / class | Purpose and startup owner | Shutdown / crash owner | Scope and cardinality |
| --- | --- | --- | --- |
| Local stdio frontend / on_demand_local_companion | Agent host launches the installed serve command; [server](../src/matlab_companion/server.py) delegates work through [client](../src/matlab_companion/client.py) | Host owns its frontend; frontend close does not cancel accepted jobs or signal the coordinator | Multiple frontends may share the same OS-user/resolved-root scope |
| Coordinator / durable_job_service | [Coordinator launcher](../src/matlab_companion/coordinator.py) starts an independent process on demand; Setup can explicitly start it | Coordinator owns accepted queue/recovery; idle exit follows no active work or handlers; crash recovery preserves uncertain effects | One Core at a time under the root lifetime lock; configuration fingerprint, instance ID, version/protocol, executable and PID/creation identity identify the owner |
| Official backend and fresh MATLAB session / native_session_bound_bridge | [Backend](../src/matlab_companion/backend.py) starts the pinned private MathWorks backend and job-owned MATLAB execution | [Core](../src/matlab_companion/core.py) owns job disposition; [native observer](../src/matlab_companion/native_session.py) records independent exit evidence | One execution worker; job/session identity and held process handle are distinct from coordinator identity; never attach to or close an unrelated session |

There is no remote connector, tunnel, Windows service or boot/logon autostart.
These components do not inherit a persistent connector's startup policy.
MATLAB licensing is user-owned and remains outside source and cloud environments.

The scope uses the resolved installation/state root and effective configuration
under the OS user. Windows IPC is a same-user named pipe that rejects remote
clients; endpoint peer/process identity is checked. Unix socket support does not
establish Linux/macOS native MATLAB support. Path resolution is implemented;
complete alias/case/junction equivalence remains a separate acceptance concern.

Source of truth: [the bundle builder](../scripts/build_windows_bundle.py)
generates Start Setup.vbs and Run Self Test.cmd;
[CLI](../src/matlab_companion/__main__.py) and
[Setup](../src/matlab_companion/setup_ui.py) propagate the selected root and manage
the named Codex connection through the official CLI. Current-device shortcut and
upgrade observations are dated evidence, not proof of a general installer for
every device. Installed-file edits are not product fixes.

## State, readiness and retry contract

Passive status/help/schema paths do not start a worker. Ordinary valid job,
inspection or artifact requests can start the coordinator and recover previously
accepted work. Reading a job through such a path is not guaranteed to be passive.

- The frontend checks the published coordinator record against process creation
  identity, protocol/version and configuration. Conflicting or unverifiable live
  owners are preserved.
- Startup is serialized by a root startup lock. Windows process breakaway is
  mandatory; rejection has no ordinary-child fallback.
- Readiness polling is bounded to 15 seconds after spawn. IPC connect/send/receive
  budgets are 3/3/20 seconds. There is no automatic RPC retransmission following
  an unconfirmed response.
- Ready means the local IPC owner published its record. It does not prove MATLAB
  or license readiness, fresh host discovery, a successful scientific call or
  artifact delivery. A record is checked when used; there is no general external
  health supervisor or OS restart service.
- The usual idle interval is 30 seconds; explicit Setup start uses 300 seconds.
  Idle exit requires no active work or request handlers. An idle_degraded receipt
  retains active/quarantine evidence and makes no native-exit claim.

### Open startup-attempt gap

Current [client startup](../src/matlab_companion/client.py), lines 68–98,
holds a spawned process only in a local variable. If readiness is unconfirmed
before coordinator.json exists, that invocation does not spawn again, but a
later invocation may make another launch attempt. Persistent spawning/failed/
unconfirmed attempt ownership is missing. This is a source-confirmed gap;
delayed-ready failure injection has not yet reproduced it.

The coordinator lifetime lock precedes Core construction and prevents a second
simultaneous Core. This finding does not establish duplicate scientific execution.
Core construction can recover accepted queued work before ready is published.
An unready process therefore must not be blindly terminated.

### Uncertain effects and native identity

Preserve the original job ID, idempotency key, dispatch, native session, receipt
and artifacts after any possibly accepted operation. Reconcile the same job;
a lost response, output-format failure or delivery error never permits automatic
scientific replay. Delivery retries use the original artifacts.

Dispatched work whose owner disappeared becomes unknown/quarantined when
quiescence is unconfirmed. Eligible accepted-but-undispatched work can recover
under its retained intent. Cancellation requested, receipt completion, backend
return, native exit and delivered files remain different observations. A late
receipt alone cannot erase uncertainty about native exit.

The native observer validates job/session/launcher binding and process birth/
executable evidence before holding a query-only Windows handle. PID alone is
insufficient. Setup's quarantine clearing requires explicit confirmation of the
owned session's stop, exact unchanged marker checks and free execution/recovery
locks; it preserves a receipt and does not terminate MATLAB. See
[executor recovery](INSTALLATION.md#executor-recovery).

## Events and acceptance limits

| Event | Implemented behavior / recovery | Evidence or gap |
| --- | --- | --- |
| Host launch / individual frontend EOF or disconnect | A valid request may start the independent owner; frontend close does not cancel accepted work | Historical native disconnect case passed with a prestarted coordinator; whole-host/outer-Job termination is not covered |
| Concurrent frontends / delayed ready / retry | Startup and lifetime locks plus identity checks constrain ownership | Portable concurrency evidence exists; the cross-call startup-attempt gap above remains open |
| Coordinator crash / next explicit start | Reconcile retained intent; eligible undispatched queue can resume; uncertain dispatched work is not replayed | Historical crash case retained unknown/quarantine; observer uncertainty remained even when an external held handle later proved exit |
| Boot / logon / reboot | No autostart; next explicit host/Setup start performs ordinary reconciliation | No continuous execution promise through reboot; actual reboot recovery unverified |
| Sleep / resume / logoff / shutdown | No dedicated OS-event hooks or guaranteed job survival; reconnect to the same root and reconcile | Actual event acceptance unverified; do not reboot or log off an active workstation as an incidental check |
| Network unavailable / restored | Local IPC has no tunnel reconnect loop; backend acquisition, host connectivity and licensing have separate dependencies | Offline or network-restoration native/license behavior unverified |
| Manual stop / startup disabled | No explicit service shutdown command or boot registration; host can stop its frontend; idle exit and explicit per-job cancellation have separate meanings | Frontend exit is not service stop; disabling a host connection is not a native cancellation claim |
| Upgrade / reinstall / rollback | Setup preserves settings; connection reuse/undo is fingerprint-scoped; conflicting live runtime/configuration owners are retained | Historical current-device alpha.2-to-alpha.3 upgrade passed; reinstall/downgrade and broad live-owner upgrade behavior unverified |
| Uninstall / retained data | Setup can undo only its unchanged owned connection; it retains jobs, original files and other plugins | No general uninstall or job-removal action; no automatic expiry; removal acceptance unverified |

## Evidence ledger

The 2026-09-19 takeover verification read source and metadata only: local/live
GitHub branch identity, enabled installed Alpha.3 connection/plugin, shortcut,
manifest identity and a bounded sample of 11 installed files. The manifest
contains 3,991 entries; this sample did not repeat the complete outgoing
integrity audit and did not execute the runtime. It supplies no new native,
license, host-model or OS-event acceptance.

| Layer | Evidence and status |
| --- | --- |
| Portable CI | [Historical runtime CI](../verification/ci-v0.1.0-alpha.3.json): Windows 364 passed/6 skipped; Ubuntu 363/7; schemas, stdio and public audit. A startup capability skip is not a positive launch result |
| Exact package | [Historical package audit](../verification/package-v0.1.0-alpha.3.json): 3,991 files, relocated path, bundled Python and hidden Tk; no visible-wizard/fresh-device claim |
| Native lifetime | [Historical three cases](../verification/native-r2-v0.1.0-alpha.3.json): disconnect, explicit cancellation, crash/quarantine; one native entry each and preserved synthetic sentinel |
| Native science / originals | [Historical six cases](../verification/native-v0.1.0-alpha.3.json): five operations, 43 original-file readbacks and six held-handle native exits on R2026a Update 5 |
| Installed upgrade | [Historical current-device receipt](../verification/local-upgrade-v0.1.0-alpha.3.json): settings/jobs/Alpha.2 and unrelated connections preserved; no reinstall/downgrade/removal acceptance |
| Host/model / delivery | [Historical Codex CLI workflow](../verification/codex-r2-v0.1.0-alpha.3.json): passed after correction, first attempt false, one scientific job and seven original local deliveries; Terra max requested, resolved model/effort unconfirmed |
| Cloud / other hosts | [Saved cloud receipt](../verification/cloud-environment.md) is Alpha.1 evidence from 2026-09-15; Alpha.3 saved-container, GUI host, ChatGPT Chat/local Work/cloud Work/Claude/WorkBuddy workflows and attachments remain unverified or unimplemented |
| OS / fresh device | Whole-host, reboot/logon/logoff/sleep/resume and new-device acceptance remain open; Linux/macOS native execution is unsupported |
| This documentation adoption | CONFIRMED document checks: five exact upstream copies, 87 local links and two Markdown anchors; public-source audit passed for 100 files; diff whitespace check passed. No runtime or deployment claim follows |

## Migration and next gates

Shared contract adoption and verified single Product Max ownership are complete
at this documentation stage. Runtime conformance and
[CB-2026-001](../governance/incidents/CB-2026-001.md) remain open.
Governance owns the shared incident and migration ledger; this repository owns
its implementation and evidence.

The next engineering deliverable is a concrete startup-attempt design and diff
plan for governance review, not implementation in this documentation change.
The proposed seam is client.py / coordinator.py with bounded storage helpers and
coordinator/recovery tests. Required invariant: persist attempt intent before
anything can spawn, reconcile that same canonical owner before a new launch,
and preserve ambiguous/pre-ready ownership without cancellation or science replay.

The first non-native gate must cover delayed ready plus a second caller (one
spawn), late readiness bound to the original identity, pre/post-spawn failures,
client loss during pre-ready recovery, concurrent roots and stale/PID-reused
identities. Exact-package, installed-current-device, native and OS-event gates
are separate and remain gated. R3 original-file delivery work remains deferred.

Distribution gap: the existing bundle builder copies docs and selected root
files, but does not yet include all newly adopted root/governance/template
dependencies. This repository-only migration neither rebuilds nor deploys the
Alpha.3 package. A future packaging change must include the required documents
or reviewed versioned references and validate packaged links before release.

Rollback of this adoption is a documentation revert only; it does not touch
settings, accepted work, native sessions or installed Alpha.3/Alpha.2 runtimes.
No runtime/schema/data migration is introduced.

## Shared provenance

The following files are unmodified copies from Chembridge commit
[922d95041b3b857f6ba11fbfb2817b18712ef605](https://github.com/saigyujikingyo-png/chembridge/commit/922d95041b3b857f6ba11fbfb2817b18712ef605).
They are deliberately adopted, not assumed to update automatically.
The local incident entrypoint links the immutable upstream audit and current
product record; it is not a copied or current incident-closure certificate.

| Local file | SHA-256 |
| --- | --- |
| [Principles](../DEVELOPMENT_PRINCIPLES.md) | ac895ed5567a1dc7a141a70747cb0d9fa61d659eccd8b583e02cae0d06e6036f |
| [Storage](../CLOUD_STORAGE.md) | 5afb82c9af39f48c3798a5c57c83f65fb5ec9f438dc17cfe95760b3e806a4783 |
| [Lifecycle contract](../RUNTIME_LIFECYCLE.md) | 375426ebe9e5391572bd278c944b625876e3e62f56702af3999571c087cb3463 |
| [Ownership contract](../governance/OWNERSHIP.md) | f939c6cfb9d6b97c574d964c3588626ab02458279b39fa9567adb98c4a7eb9e6 |
| [Lifecycle template](../templates/LIFECYCLE_RECORD.md) | 2145b0877651066c0c2f455cc608aa81399e7abdfdc1d844e8935f3346aeb72f |
