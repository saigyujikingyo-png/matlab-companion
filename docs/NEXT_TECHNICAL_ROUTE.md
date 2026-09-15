# Next technical route

Date: 2026-09-15. **R1 implemented with recorded acceptance. R2/R3 and later options remain proposals.**
Current evidence is in [R1 reliability](R1_RELIABILITY.md).

## Decision

The next release should make the existing five operations dependable in ordinary
installed use. Keep one host-neutral core, six public tools, the locked Python
environment and the accepted MathWorks backend. Reliability, recoverable jobs
and usable original-file delivery take priority over additional recipes or hosts.

The owner approved **R1 below**. That approval is not acceptance of every later host, a shared
MATLAB service, an automatic dependency upgrade or a warm-session implementation.

## Baseline alpha before R1: what the evidence supported

The baseline runtime was `c5c73174f3507f5291df5fbcea28a67795ea0763`, packaged as
`0.1.0a1`. Icon assets, adapter metadata, local installation and planning records
do not change its calculation or recovery code.

| Area | Assessment |
| --- | --- |
| Scientific foundation | Useful bounded alpha: five operations, explicit methods/units, selected numerical fixtures, native MAT/FIG reopening and independent scripts. Six final-package cases passed on R2026a Update 5. |
| Installation today | Current-device installation, registered Codex command, enabled personal plugin, cached icon and Start-menu shortcut verified. A separate installed kinetics job produced seven files with local hash readback; independent analytic error was below `1e-8`. Visible wizard, fresh device and upgrade/removal are still separate gates. |
| Interruption today | The installation probe initially read a nested job response incorrectly and closed its client. The original dispatched job was preserved as unknown, with no native receipt or outputs observed. It was reconciled without replay; quarantine was cleared only after process-absence and lock/marker checks. The later kinetics job was a different operation, not a replay. |
| Model usability | Earlier full Terra max calibration/edit/delivery passed after 14 rejected calls and 66 calls overall. A later eight-call revision passed, but has a different scope. Today's installed MCP client is not a fresh host-model benchmark. |
| Routine-use readiness | Partial. The static review identifies diagnostic side effects, root inconsistency, an execution/quarantine ordering risk and misleading over-limit resource routing. These prevent a broader reliability claim. |

Evidence: [independent review](ALPHA_REVIEW_2026-09-15.md),
[installation](../verification/local-installation-2026-09-15.json),
[installed native case](../verification/local-installation-native-2026-09-15.json),
[interrupted probe](../verification/installation-probe-interruption-2026-09-15.json),
[release status](STATUS.md).

## Architecture direction

```mermaid
flowchart LR
    H[Agent hosts] --> A[Thin MCP adapters]
    U[Setup and recovery UI] --> C[One resolved installation configuration]
    A --> D[Passive diagnostics and contract validation]
    A --> J[Durable job commands and artifact service]
    C --> D
    C --> J
    J --> S[Per-user coordinator: later R2]
    S --> W[Owned worker: fresh MATLAB session]
    W --> B[Official MathWorks MCP backend]
    B --> M[Licensed local MATLAB]
    W --> R[Validated receipts and immutable artifacts]
    R --> J
    J --> L[Approved local delivery and readback]
```

This is the target design, not the current process topology. R1 fixes the
existing topology first. R2 separates the coordinator's lifetime from an
individual MCP client only after the R1 state transitions are proven. A public
network listener and a database are not prerequisites for that local change.

## R1 — Repair the current execution and diagnostic boundaries

Proposed scope: CLI/setup entrypoints, configuration propagation, core execution
transitions, backend identity and the existing resource response. Preserve the
scientific recipes and the public tool names.

1. **Passive diagnostics.** Construct a read-only status view without queue
   recovery or a worker. Make service startup recovery an explicit internal
   operation. A previously accepted, undispatched request may resume only under
   the documented service policy; `status`, `self-test` and setup checks cannot
   authorize that transition.
2. **One installation root.** Resolve configuration once and pass it through
   setup, connection, diagnostics, job store and `OfficialBackend`. An explicit
   `--root` must reach the GUI as well. Test two distinct roots with deliberately
   different installation paths and an unconfigured default root.
3. **Execution ownership and quarantine.** Commit the terminal or
   unknown/quarantined transition while still holding execution ownership.
   Another coordinator must not dispatch between lock release and quarantine
   publication. Record an instance UUID plus process creation identity, rather
   than relying on a PID that can be reused. Keep dispatch identity, MATLAB
   session identity and native-stop evidence separate.
4. **Truthful large-file routing.** If an artifact cannot be read through the
   advertised resource route, return the implemented approved-local-delivery
   choice. Keep the size/hash metadata. Do not return an unreadable link as an
   available alternative or invent a host attachment reference.

R1 acceptance is specific: persisted queued jobs remain untouched by all passive
entrypoints; two-coordinator fault injection cannot pass an unresolved execution;
crash/timeout/late-receipt cases do not replay a dispatch; custom roots stay
isolated; and both sides of the 16 MiB resource boundary report a usable route.
Run the native lifecycle case with an unrelated MATLAB session open and prove
that session was not attached to, altered or terminated. Portable tests alone
cannot close this native gate.

## R2 — Make installed jobs survive ordinary client behavior

Use one on-demand coordinator per user and resolved installation root, with thin
stdio front ends. On Windows, evaluate a user-scoped named pipe and explicit
access control. Retain the small file-based job store unless measurement shows
it cannot meet the required atomicity or concurrency contract. Do not introduce
an always-on service by default.

- A client disconnect abandons its wait, not ownership of the scientific job.
  A separate explicit cancel request changes the job's intent. Coordinator loss
  still produces an unknown outcome until a native receipt or stop evidence is
  reconciled.
- Specify and verify the official backend's owned process/session boundary
  before adding termination behavior. A backend exit or absent response is not
  itself proof MATLAB stopped. Never use process-name-wide termination.
- Define idle exit, maximum queued work, storage accounting and explicit
  retention. Retain scientific originals and unknown-job evidence until an
  authorized removal action; ordinary cache expiry must not delete them.
- Add compact factual phases and a monotonic event sequence. Use an optional
  bounded wait on `matlab_job` that returns at a meaningful change, completion or
  time limit. Start with a short limit within the host's measured timeout.
  Unknown progress totals stay unknown; do not manufacture percentages.
- Keep result nesting and identifiers consistent across help, schemas, examples
  and installed smoke clients. The installation probe's parsing error is a
  concrete reason to validate consumers against the public envelope.

Gate: two installed clients can observe the same job; closing either client does
not lose execution ownership; restarting the coordinator never replays a
dispatched operation; cancellation, late completion and quarantine are distinct;
and idle shutdown leaves no unaccounted owned session.

## R3 — Complete the ordinary-user analysis and delivery workflow

Keep native execution and delivery independently recoverable.

- Represent approved output folders by stable setup-selected identifiers for a
  proposed multi-file delivery action. Internally resolve full filenames from
  the immutable artifact manifest. Preserve the current single-file action for
  existing clients and version any semantic changes explicitly.
- Stage a copied file in the destination directory, verify its size/hash, then
  publish it atomically. Reuse identical completed files; preserve conflicting
  files. A transfer retry reuses existing bytes and never starts MATLAB.
- If the matched benchmark shows per-file calls remain a material bottleneck,
  add a bounded batch action under `matlab_artifacts`, with per-file outcomes
  and resumable transfer receipts. Avoid adding many overlapping public tools.
- Distinguish axis-label presentation from unit metadata. A unit change needs a
  defined numerical transformation and propagation to native data/scripts, or
  clarification/rejection. Unchanged curves alone cannot certify a unit change.
- Complete visible setup, reconnect, repeated installation, upgrade and removal
  on a second user/device. Preserve existing connections and research outputs.
  Keep the designed icon consistent across the plugin, installed entry and GUI.

Gate: an installed, projectless natural-language workflow performs the same
calibration, continued revision and original-file delivery as the benchmark,
with native reopening and destination readback. Record failures and human
corrections, not merely the final result. Exercise interrupted and conflicting
delivery separately. Validate fixed-zero/weighting/unit-edit scientific branches
before extending their acceptance claims.

## Protocol compatibility and backend policy

The design retains the accepted official backend **0.13.0** and Python SDK
**2.2.0** until a measured requirement justifies a change. Public host protocol
and private backend protocol are separate connections with separate negotiated
capabilities.

The [MCP 2026-07-28 changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)
changes discovery and HTTP lifecycle and moves Tasks into an optional extension.
The [SDK 2.2.0 notes](https://github.com/modelcontextprotocol/python-sdk/blob/v2.2.0/docs/whats-new.md)
state that the new Tasks extension is not implemented there. Therefore the
existing `matlab_run`/`matlab_job` contract remains the first target; add an
extension adapter only after SDK and target-host support are demonstrated.
Test legacy and modern discovery independently, while preserving compact
structured output, server-side validation and matching JSON text fallback.

The complete source rationale is in [official-source notes](ROADMAP_SOURCE_NOTES_2026-09-15.md).
Do not implement private vendor connector RPCs or replace the official backend
merely because an alternative API exists.

## Later options, subject to separate evidence

**Warm MATLAB sessions:** only after R1/R2, with measured startup/compute/export
time and a tested reset boundary for variables, paths, working folder, figures,
random state and warnings. Compare the same workload; keep fresh sessions as
the default until isolation and material benefit are demonstrated.

**One additional host:** choose from actual user demand. First inspect its
connection, authentication and original-file receiving contract. Reuse the
same core; add only the missing adapter. A local MCP path is not a ChatGPT
attachment, and successful Codex use does not certify another host.

**Remote execution:** a later paired, single-user device-executor design with
revocation, offline/reconnect behavior, bounded transfer and verified receiver
references. It needs its own vendor/entitlement and host checks. A centralized
multi-user MATLAB service is outside this proposal.

**Additional science:** extend the existing five operations' scientific branch
coverage before choosing a new recipe. General evaluation, Live Editor/MLX,
Simulink and toolbox expansion are not in R1–R3.

## Measurement and release gates

Use GPT-5.6 Terra with max reasoning when actually available. Match input, goal,
required artifacts, host configuration and enabled plugins before comparing
results. Separate startup, computation, native verification, model/tool time,
copy time, peak memory and retained disk. Record actual input/cached/output/
reasoning counters; these do not by themselves establish a billed saving.

Each candidate keeps separate rows for source tests, installed runtime, native
science, native lifecycle, visible setup, model behavior, original-file receipt,
cloud development and release integrity. Publish an alpha only for the scopes
that passed; do not turn a repaired diagnostic or schema check into a stable
release claim. Retain the current package as the explicit rollback artifact.

**Current boundary:** the owner authorized R1 implementation and verification.
R2/R3 and later options remain designs. Finish the R1 gates and report their
actual evidence before beginning a later increment.
