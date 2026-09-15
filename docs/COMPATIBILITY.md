# Compatibility and acceptance

Updated: 2026-09-15. Product version: **0.1.0a1, development preview**.

At `6ac645d037992d1a565272f70f5e77815d69cc80`, five scientific operations passed
local native cases, a clean Windows checkpoint bundle passed relocation,
protocol and hidden-Tk checks, and a focused model-driven revision passed.
The earlier complete model workflow passed after corrections at `cf4a705`.
Windows/Ubuntu CI and cloud-container evidence below retain their own tested
commits. No record here certifies later source or a later final archive.
Visible setup, a new device and cross-host delivery remain separate gates.

The [architecture](ARCHITECTURE.md) is the approved planning snapshot.
This document describes the implementation and evidence currently available.
`READY` below applies only to the named, exercised check; `PARTIAL` means
implementation or evidence remains incomplete; `UNVERIFIED` means no matching
acceptance run is recorded.

## Execution and platform matrix

| Area | State | Evidence and limit |
| --- | --- | --- |
| Windows local native recipes | READY for recorded checkpoint | Six cases cover five operations in [native acceptance](../verification/native-release.json), at `6ac645d` on Windows 11 with Python 3.12.14. Runtime reports MATLAB `26.1.0.3346908 (R2026a) Update 5`. This is one development device. |
| Official MathWorks backend | PARTIAL | The implementation pins MATLAB MCP Server `0.13.0`, verifies the selected binary digest, requests `new` sessions with `nodesktop`, and disables upstream telemetry. The native cases exercised this route. Additional lifecycle and device acceptance remain separate. |
| Python core | READY for recorded portable CI | [CI run 35000493121](https://github.com/saigyujikingyo-png/matlab-companion/actions/runs/35000493121) passed on Windows and Ubuntu at `cf4a705`, using the Python 3.12 configuration and locked dependencies. Other Python/OS combinations remain unverified. |
| Other MATLAB releases or update builds | UNVERIFIED | Upstream version support is not Companion acceptance. Each advertised combination needs native cases and artifact reopening. |
| Linux and macOS native execution | UNVERIFIED | Backend asset mappings exist in source; they do not establish installation, activation or working MATLAB execution on these systems. |
| Codex cloud development environment | READY for historical recorded checkpoint | The Linux universal container at `cf4a705` used Python 3.12.13 and passed setup/maintenance, 163 tests in 5.66 s, Ruff, 22 schemas, real stdio and a 36-file public audit. Earlier `f3e1e67` results remain in [cloud verification](../verification/cloud-environment.md). These runs do not certify `6ac645d`, later source, a model task or desktop dispatch. |
| University/account entitlement | UNVERIFIED beyond this local run | Successful native execution is not an entitlement audit for another device, toolbox, account, shared service or remote deployment. |

The current native receipt binds the run to `6ac645d`, Python 3.12.14,
Windows 11, backend 0.13.0 and hashes of the executed MATLAB helpers. It
records the actual MATLAB version, job IDs, results, artifact sizes/hashes
and local delivery readback. Earlier [first-run evidence](../verification/native-acceptance.json)
is historical; it is not substituted for the current checkpoint.

## Scientific operations

All current operations use packaged MATLAB helpers and validated parameters.
There is no public arbitrary MATLAB evaluator. CSV/TSV inspection and staged
numeric input are implemented; arbitrary external MAT/FIG loading is not an
accepted input route. Figure revision accepts a verified Companion artifact.

| Operation | Native case evidence | Scope and boundary |
| --- | --- | --- |
| `data_profile` | Five-row numeric fixture; native MAT reopen and local file readback | Reports columns, counts and extrema. The receipt correctly leaves numerical-analysis and script-rerun flags false; this operation does not produce a figure or standalone analysis script. |
| `plot_xy` | Five-row fixture; numerical preservation, MAT/FIG reopen, standalone script rerun and local file readback | Explicit x/y columns and units. Additional data shapes and visual publication quality need separate checks. |
| `linear_calibration` | Free-intercept calibration with relative weights and known sigma; numerical checks, MAT/FIG reopen, script rerun and local file readback | The current checkpoint covers these two weighting cases; a separate TSV regression also passed. Fixed-zero intercept and further edge cases must not inherit these native passes. |
| `first_order_kinetics` | 101-point decay fixture; maximum absolute analytic comparison error `4.260867214611608e-10`; native reopen, script rerun and local file readback | Recorded initial concentration `2 mmol/L`, rate `0.25 s^-1`, duration `8 s`. This fixture is not validation of a general kinetic model or arbitrary solver. |
| `revise_figure` | An owned calibration figure receives a title revision; curves preserved, native reopen, script rerun and local file readback | Earlier artifact retained. Other labels, limit changes and supported figure-object combinations require their own preservation cases. |

Applicable original outputs include `.mat`, `.fig`, independently runnable
`.m`, CSV, PNG, PDF and method JSON. A hash establishes byte identity; native
reopen and numerical comparisons establish different properties. The current
run records preservation of the original input. The assistant also visually
inspected the TSV calibration and light-style kinetics exports from the
[separate regression](../verification/native-tsv-acceptance.json). This does
not establish a visible MATLAB editing session or review of every possible
export/figure combination.

Live Editor/`.mlx`, Simulink, optional scientific toolboxes, general code
execution, existing user-session attachment and remote execution are outside
this preview's implemented acceptance scope.

## Protocol, files and host matrix

The real stdio smoke check exercises initialize, discovery of six tools and
their output schemas, status/help calls, schema resources, serialized JSON
fallback equality, and a rejected invalid run request. Server-side typed
validation also covers operation-specific results and dispatcher branches.
These checks exercise the protocol with a programmatic client, not a host
model following a natural-language request.

| Surface or delivery route | State | Evidence still required |
| --- | --- | --- |
| Programmatic local MCP stdio client | READY for protocol smoke scope | A successful native scientific workflow through an actual target host remains separate. |
| Approved local file copy | READY for recorded native cases | Destination byte/hash readback is recorded for the current checkpoint's synthetic case outputs; new destinations and end-user usability remain separate. |
| MCP original resources and PNG content | PARTIAL | Implemented content/resource routes preserve original bytes. A resource available to a client is not proof that a target host received or opened it. |
| Codex local model workflow | READY for recorded bounded cases | The [complete ephemeral CLI workflow](../verification/codex-benchmark.json) at `cf4a705` passed calibration, continued revision and 16 local-file readbacks after corrections. A [focused revision](../verification/codex-revision-release.json) at `6ac645d` passed with 8 calls, one run request and zero errors. Visible setup and fresh-user projectless use remain unverified. |
| ChatGPT Chat | UNVERIFIED | A supported authenticated connection/device route, actual model call and original-file delivery. |
| ChatGPT local Work | UNVERIFIED | Actual available host connection and received-file checks. The known project-sync frontend issue remains outside this product task. |
| ChatGPT cloud Work | UNVERIFIED | Remote executor connection, receiving-workspace materialization, host attachment contract and destination readback. |
| Claude local-capable hosts | UNVERIFIED | Installed adapter, tool invocation by a real model and native-artifact receipt. |
| WorkBuddy and other suitable agents | UNVERIFIED | Discover actual MCP/authentication/file capabilities, then run the same acceptance workflow. |
| GPT-5.6 Terra, max reasoning | PARTIAL benchmark | Both Codex CLI records requested this model/effort and report actual outcomes and host usage. The complete run had 66 calls, 14 rejected calls and first-attempt failure; its successful corrected workflow does not establish efficiency. The later focused revision is a separate, narrower case. |
| Other target models and ELM | UNVERIFIED | Per-host/model capability and acceptance evidence. No paid model service is provisioned by default. |

The implementation offers stdio and approved local delivery. A remote HTTP
gateway, paired executor connection and host-specific attachment adapters
are not implemented. The reserved `host_attachment` contract value does not
advertise such an adapter. Inline resource transfer is bounded to 16 MiB;
larger files require an implemented authorized delivery route.

The complete model run took 628.875 seconds and loaded unrelated installed
plugins; it is not an isolated six-tool efficiency measurement. The focused
revision disabled unrelated plugins and took 85.141 seconds. Its recorded
scope excludes a repeated full calibration/local-delivery acceptance.
Token counters and their subset semantics are recorded in [status](STATUS.md)
and the source receipts. No billing cost or savings is inferred.

## Installation, recovery and remaining release gates

| Gate | State | Practical boundary |
| --- | --- | --- |
| Windows bundle after path relocation | READY for checkpoint archive | [Clean-package acceptance](../verification/package-clean-release.json): 33,001,516 bytes, 3,957 manifest entries, clean `6ac645d` source, zero mismatches and zero unlisted files; portable self-test and bundled-runtime protocol passed after moving to a path containing spaces and Chinese characters. A later final archive requires its own receipt. |
| Graphical setup and connection management | PARTIAL | Bundled Tk 8.6.12 was constructed, updated and destroyed while withdrawn. The visible wizard and host-configuration flow have not been accepted. |
| New device/user, upgrade and repeat install | UNVERIFIED | Need isolated installation, settings preservation, path variations and real self-test. |
| Reconnect, repair, rollback and removal | UNVERIFIED | Need actual user-facing flows and retention of unrelated host settings and research outputs. |
| Jobs, deduplication and recovery | PARTIAL | Durable job records, locks, a ten-job active queue bound, cancellation flags and receipt reconciliation are implemented. A cancellation request is not proof MATLAB stopped. Timeout/quarantine behavior and late results need native lifecycle acceptance. |
| Shared coordinator and retention | PARTIAL | Cross-process locks serialize native work for one runtime root. The planned shared IPC coordinator, warm reusable session, automatic retention UI and complete resource measurements remain open. |
| Published end-user package | PARTIAL | A specific archive has passed runtime/relocation checks. Public release publication, signature/warning behavior and complete end-user release gates remain separate. |

The checkpoint package receipt records clean source at `6ac645d`, bundled Python 3.12.14,
and archive SHA-256
`b198e8417bd28dcaf9608990209dcb224a5cc42c2d0474f87b6f3ca440f4deb1`.
A focused byte scan found no exact local builder username or checkout path,
and no embedded builder metadata. That scan is not a comprehensive secret
audit. The package check did not open a visible GUI, change a host connection,
start MATLAB, download the vendor backend or establish new-device acceptance.

No stable or end-user-ready claim is made. Keep native execution, portable
tests, cloud containers, installation, model behavior, visual review and
received-file evidence separate when updating this matrix.
