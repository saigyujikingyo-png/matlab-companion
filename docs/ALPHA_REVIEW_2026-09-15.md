# Alpha review — 2026-09-15

## Decision

**Keep the release a bounded Windows alpha. Prioritize predictable installation,
diagnostics and recovery before adding scientific operations or more hosts.**
The existing native and artifact evidence supports useful work on the recorded
device. It does not yet establish dependable everyday use through an installed
host, especially after interruption.

This is an independent documentation and static-source review. No code was
changed and no new runtime, model, installation or native acceptance was run for
this review. Findings below distinguish directly observable source behavior,
unexercised failure risks and missing acceptance. The separately requested icon
and installation work can add its own receipt; it cannot close unrelated gates.

## Immutable baseline and evidence

- Published version: `v0.1.0-alpha.1` / package `0.1.0a1`.
- Reviewed runtime source: `c5c73174f3507f5291df5fbcea28a67795ea0763`.
- Documentation/evidence baseline: `a987b494ef677978f86af84210da9f667f6fa589`.
- Windows ZIP: 33,013,051 bytes; SHA-256
  `8b22ed6b715f3f7ec4f474973db63d24612fc1ce27179e9ccdf62e9263a7ae2a`.

Later metadata or documentation work does not change the source identity of the
published runtime. Historical model receipts remain bound to their own commits.

| Gate | Evidence already recorded | What it establishes / does not establish |
| --- | --- | --- |
| Portable source | [Final CI receipt](../verification/ci-v0.1.0-alpha.1.json): Windows 164 passed; Ubuntu 163 passed, one Windows-only skip; Ruff, 22 schemas, stdio and public audit | Contract and portable behavior at the release commit; not native or host acceptance |
| Final package | [Package receipt](../verification/package-v0.1.0-alpha.1.json): clean source, 3,963 manifest entries, no mismatch or unlisted files; relocated runtime and hidden Tk passed | These exact bytes run from a path containing spaces and Chinese characters; visible setup and a new device remain separate |
| Native science | [Final archive native receipt](../verification/native-v0.1.0-alpha.1.json): six cases across all five operations on Windows 11 / MATLAB R2026a Update 5 | Applicable numerical checks, native reopen, script rerun and local byte/hash readback; one device/build and selected inputs only |
| Complete model workflow | [Benchmark](../verification/codex-benchmark.json), `cf4a705`: calibration, revision and 16 requested local files verified after corrections | Actual model work, but 66 calls, 14 rejected calls, 628.875 seconds, first-attempt failure and unrelated plugins loaded |
| Focused model revision | [Revision receipt](../verification/codex-revision-release.json), `6ac645d`: 8 calls, one run, zero errors, 85.141 seconds | A narrower isolated revision passed; it is not a repeated complete workflow or final-commit efficiency result |
| Distribution | [Publication receipt](../verification/release-v0.1.0-alpha.1.json): downloaded asset/checksum match the tested archive | Reproducible release delivery; not installation, model receipt or a stable-release pass |

The baseline [compatibility matrix](COMPATIBILITY.md) correctly keeps visible
setup, new-user/device use, upgrades, reconnect/repair/rollback/removal, native
failure recovery and other hosts open. Saved cloud-container tests are useful
development evidence, not a cloud model or remote MATLAB execution route.

## Foundations worth retaining

The host-neutral six-tool boundary, official backend pin and new owned-session
mode are appropriate for the current scope. Strict output and operation-result
models reject malformed success responses and nonfinite values. Compact job
responses keep detailed schemas/results available on demand. The public figure
revision schema correctly removes the internal `source_figure` path; callers
select verified owned artifacts instead.

Scientific choices are explicit: units and column selection, free/zero intercept,
relative weights versus known sigma, finite input checks and stated uncertainty
availability. Recorded numerical checks are complemented by native reopen and
standalone script rerun. Immutable artifact manifests and hash checks before
read, delivery and revision protect earlier outputs from being silently
re-trusted after alteration. These are substantive alpha capabilities.

## Prioritized findings

Priorities describe the next development sequence, not claims of an observed
production incident. P1 should block broader routine-use claims; P2 should close
before the corresponding configuration or delivery route is advertised.

### P1 — Diagnostics can resume previously queued native work

**Confirmed source behavior; high confidence.** The CLI constructs `Core` for
both `status` and `self-test`. Construction invokes `_recover_jobs`, which submits
orphaned, fully registered queued jobs. `close()` then waits for the worker.
Consequently a diagnostic invocation against a populated runtime root can launch
previously authorized native work and wait for it. The status handler itself
does not launch MATLAB; the side effect comes from startup. The GUI's
`setup_status` deliberately avoids constructing `Core` and is already passive.

Evidence: [CLI](../src/matlab_companion/__main__.py), lines 13–49;
[core](../src/matlab_companion/core.py), lines 62–75 and 112–185;
[setup status](../src/matlab_companion/setup_ui.py), lines 397–423 at the reviewed
runtime commit. The existing queued-recovery test exercises automatic recovery,
not the diagnostic entrypoint's promise.

**Decision:** separate observing state from authorizing scheduler recovery.
Diagnostics must never resume a queue. Define and expose when normal service
startup may resume an already accepted, undispatched request. Acceptance must
include a persisted queued job and prove that status/self-test leave it queued
without starting the native backend.

### P1 — Failure quarantine is published after releasing the execution lock

**Design risk from a concrete source ordering; high confidence in the ordering,
not reproduced in this review.** `_execute` holds `.execution.lock` while calling
the backend, but its outer exception handler writes `executor-quarantine.json`
after the `with` block releases that lock. A second coordinator with a queued job
can acquire the lock in that interval, see no quarantine and start another
dispatch while the preceding outcome is still unconfirmed. The one-worker pool
prevents this interleaving within one `Core`; it does not serialize the exception
handler against another `Core` using the same root.

Evidence: [core](../src/matlab_companion/core.py), lines 475–545. The recovery
regressions cover missing receipts, dispatch loss, duplicate registration and
lock timeout; those cases do not demonstrate this inter-coordinator boundary.
The same lifecycle design currently checks owner liveness by PID alone and
writes `coordinator_identity: null` (lines 129 and 512). A reused PID can therefore
be mistaken for the old coordinator; no process-incarnation proof is present.

**Decision:** define one durable transition from owned execution to terminal or
unknown/quarantined state before releasing execution ownership. Bind recovery
to an identifiable coordinator/session incarnation, and keep cancellation
requested distinct from confirmed exit. Require deterministic multi-coordinator
fault injection plus a bounded owned-session native interruption/late-receipt
case. Defer warm session reuse until these properties are demonstrated.

### P2 — A selected runtime root is not propagated consistently

**Confirmed source behavior; high confidence.** `configured_core` reads input and
output settings from `--root`, while `Core` constructs `OfficialBackend()` with
its default root. Backend binary discovery and the MATLAB installation setting
can therefore come from a different root. The `setup` CLI branch also calls
`setup_main()` without passing `args.root`. The ordinary default-root path does
not suffer this mismatch, but custom-root isolation is unreliable.

Evidence: [CLI](../src/matlab_companion/__main__.py), lines 13–35;
[core](../src/matlab_companion/core.py), line 66;
[backend](../src/matlab_companion/backend.py), lines 119–136.

**Decision:** one resolved installation/configuration identity must flow through
setup, connection, diagnostics and execution. Verify two roots with deliberately
different settings and backend locations, including an absent default setup.
Do not silently combine them. This is a consistency repair, not a requirement to
build a multi-profile product now.

### P2 — Large-file discovery advertises an unreadable resource route

**Confirmed source behavior; high confidence.** `matlab_artifacts.read` returns a
`ResourceLink` for an artifact larger than 16 MiB, but reading that same URI
through `resource_content` rejects it at the same limit. Its structured delivery
metadata still describes an available MCP resource. Artifacts up to 512 MiB are
accepted, so this route matters for valid jobs. Authorized local copying remains
available and is the implemented way to receive these larger files.

Evidence: [server](../src/matlab_companion/server.py), lines 97–127 and 158–178;
[core](../src/matlab_companion/core.py), lines 771–799.

**Decision:** advertise an executable delivery choice. For this local alpha,
explicitly require local delivery for over-limit files rather than implying a
readable fallback resource. Retain compact metadata and original-byte readback.
Also define interrupted-copy recovery: the current copy writes directly to a
new final destination, so interruption can leave a partial file that a retry
correctly refuses to overwrite. This is an unexercised recovery scenario, not a
claim that a recorded delivery failed. Staged publication or another bounded
retry design must preserve unrelated destination contents.

## Scientific and usability limits that need decisions

**Scientific semantics:** the accepted revision case changes a title. The
implementation also permits arbitrary axis-label text while preserving the
numeric curves. It cannot distinguish a typography change from changing
`mmol/L` to `mol/L`. The approved [architecture](ARCHITECTURE.md) requires either
the corresponding value transformation or clarification for such a change.
Before claiming general label revision, separate label presentation from unit
metadata or reject ambiguous unit changes. This is a design gap; no incorrect
unit conversion is asserted in the recorded title-only case.

**Native coverage:** fixed-zero calibration, further uncertainty/rank/constant
response cases, zero initial concentration and label/limit preservation need
their own native evidence before those branches inherit a pass. Portable schema
tests cannot validate the MATLAB numerical implementation. Existing curves,
tables and standalone scripts remain the acceptance artifacts for each case.

**Model usability:** the complete historical benchmark exposes a costly error
and correction path. Later argument descriptions and the focused revision are
encouraging but do not quantify full-workflow improvement. Repeat one installed,
projectless calibration → revision → delivery task with the same scope and
record actual model/effort, tools, errors, elapsed time, token counters and
received bytes. Separate native execution time from model/tool orchestration.
Do not infer monetary cost, quota savings or whole-workflow improvement from
different-sized runs. Introduce bounded multi-artifact delivery only if the
matched workflow shows per-file calls are a material remaining bottleneck.

## Recommended milestones and stop gates

| Sequence | Concrete outcome | Gate before proceeding |
| --- | --- | --- |
| 1. Make one installed local executor predictable | Passive diagnostics; consistent root identity; durable quarantine before releasing ownership; identifiable owner/session; clear recovery status | Regressions for the exact findings above; visible setup/reconnect/rollback preserves unrelated host settings; owned native interruption and late receipt do not replay a dispatched write or disturb another MATLAB session |
| 2. Complete one ordinary-user workflow reliably | Installed, projectless inspect/calibrate/edit/deliver path with actionable errors, usable large-file routing and interrupted-delivery recovery | A matched full model run on the exact new release candidate; original files reopen and match at the chosen destination; failure/retry preserves prior research outputs; report first-attempt and corrected outcomes separately |
| 3. Expand only a justified boundary | Close selected scientific branch and unit-edit cases; then choose one additional host or one new scientific workflow from actual user demand | Predeclared numerical/preservation fixtures for the science branch, or actual authenticated model invocation and original-file receipt for the host; a source/manifest/schema-only pass is insufficient |

Retain the official backend unless a measured, essential limitation justifies a
replacement. Fresh native jobs currently take about 11–23 seconds in the recorded
cases; profile startup versus compute/verification before choosing warm reuse.
An IPC service, remote gateway, arbitrary evaluator, toolbox integration or
additional platform is not required to resolve the current findings.

**Stop point:** this review proposes decisions and acceptance gates only. It
does not authorize or implement the next code phase. Integrate the separate
installation receipt with its actual scope, agree the next milestone, and stop
before formal development begins.
