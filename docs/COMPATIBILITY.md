# Compatibility and acceptance

Updated: 2026-09-15. Product version: **0.1.0a1, development preview**.

Five scientific operations have passed a first local native run. The real
stdio protocol smoke check has also passed. These results do not establish
ordinary-user installation, a GUI workflow, a host/model connection or
cross-host file delivery.

The [architecture](ARCHITECTURE.md) is the approved planning snapshot.
This document describes the implementation and evidence currently available.
`READY` below applies only to the named, exercised check; `PARTIAL` means
implementation or evidence remains incomplete; `UNVERIFIED` means no matching
acceptance run is recorded.

## Execution and platform matrix

| Area | State | Evidence and limit |
| --- | --- | --- |
| Windows local native recipes | READY for the first synthetic run | Six cases cover five operations in [native acceptance](../verification/native-acceptance.json), observed 2026-09-15. Runtime reports MATLAB `26.1.0.3346908 (R2026a) Update 5`. This is one development device. |
| Official MathWorks backend | PARTIAL | The implementation pins MATLAB MCP Server `0.13.0`, verifies the selected binary digest, requests `new` sessions with `nodesktop`, and disables upstream telemetry. The native cases exercised this route. Additional lifecycle and device acceptance remain separate. |
| Python core | PARTIAL | The project targets Python 3.12 with locked dependencies. Protocol and contract checks run without MATLAB. Additional Python/OS combinations need their own results. |
| Other MATLAB releases or update builds | UNVERIFIED | Upstream version support is not Companion acceptance. Each advertised combination needs native cases and artifact reopening. |
| Linux and macOS native execution | UNVERIFIED | Backend asset mappings exist in source; they do not establish installation, activation or working MATLAB execution on these systems. |
| Codex cloud development environment | READY for tested commit | Saved environment and Linux universal container verified at `f3e1e67b44a2e6758c762b98554b460e2744c7f6`, Python `3.12.13`: setup/maintenance, 157 tests, Ruff, 22 schemas, real stdio smoke and 33-file public audit passed. Later fixes require a separate run. This does not establish a model task, desktop dispatch or native MATLAB acceptance; see [cloud verification](../verification/cloud-environment.md). |
| University/account entitlement | UNVERIFIED beyond this local run | Successful native execution is not an entitlement audit for another device, toolbox, account, shared service or remote deployment. |

The native receipt records the observed MATLAB version, job IDs, results,
artifact sizes/hashes and local delivery readback. It currently does not bind
the run to a tested Git commit or a complete Python/platform/backend version
tuple. Preserve it as first-run evidence; bind final release acceptance to an
exact source/package version before claiming a release gate has passed.

## Scientific operations

All current operations use packaged MATLAB helpers and validated parameters.
There is no public arbitrary MATLAB evaluator. CSV/TSV inspection and staged
numeric input are implemented; arbitrary external MAT/FIG loading is not an
accepted input route. Figure revision accepts a verified Companion artifact.

| Operation | Native case evidence | Scope and boundary |
| --- | --- | --- |
| `data_profile` | Five-row numeric fixture; native MAT reopen and local file readback | Reports columns, counts and extrema. The receipt correctly leaves numerical-analysis and script-rerun flags false; this operation does not produce a figure or standalone analysis script. |
| `plot_xy` | Five-row fixture; numerical preservation, MAT/FIG reopen, standalone script rerun and local file readback | Explicit x/y columns and units. Additional data shapes and visual publication quality need separate checks. |
| `linear_calibration` | Free-intercept calibration with relative weights and known sigma; numerical checks, MAT/FIG reopen, script rerun and local file readback | First native evidence covers these two weighting cases. Fixed-zero intercept and further edge cases must not inherit their native pass. |
| `first_order_kinetics` | 101-point decay fixture; maximum absolute analytic comparison error `4.260867214611608e-10`; native reopen, script rerun and local file readback | Recorded initial concentration `2 mmol/L`, rate `0.25 s^-1`, duration `8 s`. This fixture is not validation of a general kinetic model or arbitrary solver. |
| `revise_figure` | An owned calibration figure receives a title revision; curves preserved, native reopen, script rerun and local file readback | Earlier artifact retained. Other labels, limit changes and supported figure-object combinations require their own preservation cases. |

Applicable original outputs include `.mat`, `.fig`, independently runnable
`.m`, CSV, PNG, PDF and method JSON. A hash establishes byte identity; native
reopen and numerical comparisons establish different properties. The first
run records preservation of the original input. It does not establish a
manual desktop editing session or human review of every exported figure.

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
| Approved local file copy | READY for first native cases | Destination byte/hash readback is recorded for the synthetic case outputs; new destinations and end-user usability remain separate. |
| MCP original resources and PNG content | PARTIAL | Implemented content/resource routes preserve original bytes. A resource available to a client is not proof that a target host received or opened it. |
| Codex local, projectless end-user workflow | UNVERIFIED | Install/connect, actual model request, continued edit and received-file reopening without a coding project. |
| ChatGPT Chat | UNVERIFIED | A supported authenticated connection/device route, actual model call and original-file delivery. |
| ChatGPT local Work | UNVERIFIED | Actual available host connection and received-file checks. The known project-sync frontend issue remains outside this product task. |
| ChatGPT cloud Work | UNVERIFIED | Remote executor connection, receiving-workspace materialization, host attachment contract and destination readback. |
| Claude local-capable hosts | UNVERIFIED | Installed adapter, tool invocation by a real model and native-artifact receipt. |
| WorkBuddy and other suitable agents | UNVERIFIED | Discover actual MCP/authentication/file capabilities, then run the same acceptance workflow. |
| GPT-5.6 Terra, max reasoning | UNVERIFIED | Exact available host/model/effort, common-case outcomes, corrections, time and actual usage where available. Protocol tests are not this benchmark. |
| Other target models and ELM | UNVERIFIED | Per-host/model capability and acceptance evidence. No paid model service is provisioned by default. |

The implementation offers stdio and approved local delivery. A remote HTTP
gateway, paired executor connection and host-specific attachment adapters
are not implemented. The reserved `host_attachment` contract value does not
advertise such an adapter. Inline resource transfer is bounded to 16 MiB;
larger files require an implemented authorized delivery route.

## Installation, recovery and remaining release gates

| Gate | State | Practical boundary |
| --- | --- | --- |
| Source/dependency setup | PARTIAL | Developer setup exists. Source installation is not the required ordinary-user installer. |
| Graphical setup and connection management | UNVERIFIED | No completed GUI acceptance is recorded. A command name or draft UI cannot establish a functioning setup flow. |
| New device/user, upgrade and repeat install | UNVERIFIED | Need isolated installation, settings preservation, path variations and real self-test. |
| Reconnect, repair, rollback and removal | UNVERIFIED | Need actual user-facing flows and retention of unrelated host settings and research outputs. |
| Jobs, deduplication and recovery | PARTIAL | Durable job records, locks, a ten-job active queue bound, cancellation flags and receipt reconciliation are implemented. A cancellation request is not proof MATLAB stopped. Timeout/quarantine behavior and late results need native lifecycle acceptance. |
| Shared coordinator and retention | PARTIAL | Cross-process locks serialize native work for one runtime root. The planned shared IPC coordinator, warm reusable session, automatic retention UI and complete resource measurements remain open. |
| Published end-user package | UNVERIFIED | Package/runtime verification, signatures or warning behavior, checksums, installation guide and exact-version release gates remain required. |

No stable or end-user-ready claim is made. Keep native execution, portable
tests, cloud containers, installation, model behavior, visual review and
received-file evidence separate when updating this matrix.
