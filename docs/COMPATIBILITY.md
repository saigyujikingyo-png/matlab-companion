# Compatibility and acceptance

Updated: 2026-09-16. Current release: **0.1.0a3, R2 Windows preview**.

R2 adds private local IPC and native exit observation. Windows native execution
requires an independently started coordinator and a verified owned MATLAB process
handle. Linux/macOS native execution is explicitly unsupported in this release
because its exit observer is not implemented there; portable Linux CI is a
separate gate. Individual frontend disconnect and complete host termination have
different scopes. See the [R2 ledger](R2_DURABLE_JOBS.md) for current evidence.
The current matrix below separates alpha.3 evidence from historical releases.

## Current alpha.3 release

Runtime `1b2eb73bcd674056cf756260ee5359c083c24afe` produced the
33,104,323-byte Windows ZIP with SHA-256
`d6a839606570d94a83407b7d1276bd2068c72c260d03cda210f33c7841b30aaa`.
The [status ledger](STATUS.md#current-r2-candidate) is the release-gate record.

| Surface / gate | State | Exact scope |
| --- | --- | --- |
| Windows and Ubuntu portable CI | PASSED at `1b2eb73` | [CI 35083094659](https://github.com/saigyujikingyo-png/matlab-companion/actions/runs/35083094659): Windows 364 passed, 6 skipped; Ubuntu 363 passed, 7 skipped. Ruff, 22 schemas, stdio and public audit passed on both. A restricted-host startup skip is not a successful startup |
| Private coordinator, wait and recovery | PASSED for recorded portable/native scope | One root/owner, no blind RPC replay, bounded wait and durable sequence. [Final-package lifecycle receipt](../verification/native-r2-v0.1.0-alpha.3.json) passed three prestarted-coordinator cases: client disconnect, explicit cancel, and crash/unknown/quarantine. This does not prove host-triggered automatic startup |
| Linux/macOS native MATLAB | UNSUPPORTED in alpha.3 | No native-exit observer on these platforms; reject before admitting a scientific job. Portable Ubuntu checks do not change this boundary |
| Exact Windows package runtime | PASSED for recorded scope | [Package receipt](../verification/package-v0.1.0-alpha.3.json): 3,991 manifest entries, zero mismatches/unlisted files, pre/post-runtime hash readback, isolated self-test, real stdio and withdrawn Tk. Prestarted coordinator exited idle with zero jobs/dispatches; this did not start MATLAB |
| Exact-package native MATLAB | PASSED for six recorded scientific cases | [Native receipt](../verification/native-v0.1.0-alpha.3.json): five operations on R2026a Update 5, 43 original-file readbacks and six held-handle-confirmed exits. Imported runtime hashes match the immutable archive manifest; no other device/MATLAB build is accepted by this run |
| Codex model and original local delivery | PASSED AFTER CORRECTION | [Combined receipt](../verification/codex-r2-v0.1.0-alpha.3.json): three actual turns, 14 calls, one scientific job, three valid waits and seven original local-file readbacks. First-attempt success is false; one missing-`job_id` delivery failed before a delivery-only correction. Requested Terra max; resolved model/effort identity is unknown |
| Current-device upgrade and registered host | PASSED for recorded scope | [Upgrade receipt](../verification/local-upgrade-v0.1.0-alpha.3.json): runtime/connection, enabled plugin cache, selected-root shortcut and backups verified; settings, prior jobs, alpha.2 files and seven other MCP entries preserved. Read-only self-test/protocol checks started no coordinator or MATLAB. Visible wizard, new device and rollback/removal were not exercised |
| Saved cloud development container | UNVERIFIED for alpha.3 | Ubuntu CI is not a saved-environment verification or remote desktop/native route; this is an explicit preview limit |
| Publication | PASSED | [Alpha.3 release](https://github.com/saigyujikingyo-png/matlab-companion/releases/tag/v0.1.0-alpha.3) and [receipt](../verification/release-v0.1.0-alpha.3.json): exact runtime tag, published digest, fresh ZIP and checksum match; alpha.2 remains retained for rollback |
| Visible setup, fresh device, host attachments and other hosts | UNVERIFIED | Require their own receiver, usability and platform evidence |

Explicitly starting the service before a client connects proves a different
route from client-triggered automatic startup. Both remain bounded to an
individual frontend disconnect, not termination of the outer host/OS job.
In the crash case, an independent held handle proved native exit while the
interrupted production observer remained unconfirmed. The existing unknown
job and quarantine were retained; observing process exit did not invent a
scientific result or authorize replay.

The [first model preparation record](../verification/codex-r2-first-preparation.json)
contains an operator path-comparison failure before any model call or scientific
dispatch. It is not a model retry. The [first actual model turn](../verification/codex-r2-first-model-attempt.json)
also stopped before any Companion call/job because the operator disabled the
required code-mode host. That override was removed only in the ignored operator.
The second actual turn completed science and waiting, but its first delivery
omitted `job_id` and was rejected. A third, delivery-only turn passed for the
same completed job. First-attempt success remains false, and no scientific
write was replayed. Across all three turns: 191.688 seconds, 277,722 input
tokens (213,504 cached), 7,236 output tokens (4,301 reasoning). The CLI did not
expose resolved model/effort metadata, and no cost or quota saving is inferred.

## Historical alpha.2 evidence

R1 runtime `41f9cf7` passed its matching Windows/Ubuntu CI, the bounded native
interruption/sentinel case and six final-package native cases across all five
operations. Package integrity and 43 original-file local readbacks passed.
[R1 reliability](R1_RELIABILITY.md) records exact receipts and remaining gates.

The [current-device alpha.2 upgrade](../verification/local-upgrade-v0.1.0-alpha.2.json)
also passed: the owned Codex connection, enabled plugin cache and Start-menu
entry were refreshed; settings, existing jobs, retained alpha.1 files and other
MCP connections were preserved. The registered command passed a read-only MCP
probe. This is not a new model, visible-wizard or clean-device acceptance.

## Historical alpha.1 evidence

The rows below retain their original alpha.1 source/runtime identities.

Current-device icon and installation results are recorded in the
[installation receipt](../verification/local-installation-2026-09-15.json).
The installed registered command completed one kinetics case with seven original
files read back. Visible setup, a new device and a new installed-host model run
remain unverified. The [independent alpha review](ALPHA_REVIEW_2026-09-15.md)
records the original reliability/configuration/delivery findings; R1 repairs are
tracked above, separately from the earlier installed case.

Final source/runtime `c5c73174f3507f5291df5fbcea28a67795ea0763` passed
Windows/Ubuntu CI, the saved cloud-container checks and final-archive runtime,
relocation and hidden-Tk checks. Six native cases covering all five operations
also passed from the exact final archive's relocated Windows runtime.
Earlier source-native cases and the focused model revision passed at
`6ac645d`; the complete model workflow passed after corrections at
`cf4a705`. These records retain their separate commits and scopes. Visible
setup, a new device and cross-host delivery remain separate gates.

The [architecture](ARCHITECTURE.md) is the approved planning snapshot.
This document describes the implementation and evidence currently available.
`READY` below applies only to the named, exercised check; `PARTIAL` means
implementation or evidence remains incomplete; `UNVERIFIED` means no matching
acceptance run is recorded.

## Historical alpha.1 execution and platform matrix

| Area | State | Evidence and limit |
| --- | --- | --- |
| Windows local native source checkpoint | READY for historical recorded cases | Six cases cover five operations in [earlier native acceptance](../verification/native-release.json), at `6ac645d` on Windows 11 with Python 3.12.14 and MATLAB `26.1.0.3346908 (R2026a) Update 5`. Retained separately from final-archive evidence. |
| Final archive native execution | READY for recorded cases | [Final native acceptance](../verification/native-v0.1.0-alpha.1.json) records `c5c7317`, the exact final archive SHA-256 and the relocated Windows release runtime: six cases cover five operations, with applicable native reopen, numerical/script checks and local byte/hash delivery readback. This remains one device and MATLAB build. |
| Official MathWorks backend | PARTIAL | The implementation pins MATLAB MCP Server `0.13.0`, verifies the selected binary digest, requests `new` sessions with `nodesktop`, and disables upstream telemetry. The native cases exercised this route. Additional lifecycle and device acceptance remain separate. |
| Python core | READY for final source CI | [CI run 35003649768](https://github.com/saigyujikingyo-png/matlab-companion/actions/runs/35003649768) at `c5c7317`: Windows 164 passed in 8.01 s; Ubuntu 163 passed, one Windows-only CLI test skipped, in 3.86 s. Both runners passed Ruff, 22 schemas, real stdio and the 44-file public audit. Other Python/OS combinations remain unverified. |
| Other MATLAB releases or update builds | UNVERIFIED | Upstream version support is not Companion acceptance. Each advertised combination needs native cases and artifact reopening. |
| Linux and macOS native execution | UNVERIFIED | Backend asset mappings exist in source; they do not establish installation, activation or working MATLAB execution on these systems. |
| Codex cloud development environment | READY for final source checkpoint | The restarted Linux universal container at `c5c7317` used Python 3.12.13 and passed setup/maintenance, 163 tests with one Windows-only CLI skip in 7.64 s, Ruff, 22 schemas, real stdio and a 44-file public audit. Earlier runs remain in [cloud verification](../verification/cloud-environment.md). This is not a cloud model task or desktop dispatch. |
| University/account entitlement | UNVERIFIED beyond this local run | Successful native execution is not an entitlement audit for another device, toolbox, account, shared service or remote deployment. |

The final native receipt binds the run to `c5c7317` and archive SHA-256
`8b22ed6b715f3f7ec4f474973db63d24612fc1ce27179e9ccdf62e9263a7ae2a`,
including execution through the relocated release runtime. Earlier
[source-native](../verification/native-release.json) and
[first-run evidence](../verification/native-acceptance.json) remain historical
and are not substituted for this archive check.

## Scientific operations and historical native cases

All current operations use packaged MATLAB helpers and validated parameters.
There is no public arbitrary MATLAB evaluator. CSV/TSV inspection and staged
numeric input are implemented; arbitrary external MAT/FIG loading is not an
accepted input route. Figure revision accepts a verified Companion artifact.
The native fixtures in this table are historical alpha.1 evidence; unchanged
recipes do not substitute for alpha.3 package/lifecycle acceptance.

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

## Protocol and historical alpha.1 host matrix

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

## Historical alpha.1 installation and release matrix

These rows preserve the alpha.1 checkpoint. The shared IPC coordinator is now
implemented in alpha.3, and alpha.2 has its separately recorded upgrade above;
neither later result retroactively changes these historical gates.

| Gate | State | Practical boundary |
| --- | --- | --- |
| Windows bundle after path relocation | READY for final archive runtime scope | [Final-package acceptance](../verification/package-v0.1.0-alpha.1.json): 33,013,051 bytes, 3,963 manifest entries, clean `c5c7317` source, zero mismatches and zero unlisted files; portable self-test and bundled-runtime protocol passed after moving to a path containing spaces and Chinese characters. Native acceptance remains separate. |
| Graphical setup and connection management | PARTIAL | Bundled Tk 8.6.12 was constructed, updated and destroyed while withdrawn. The visible wizard and host-configuration flow have not been accepted. |
| New device/user, upgrade and repeat install | UNVERIFIED | Need isolated installation, settings preservation, path variations and real self-test. |
| Reconnect, repair, rollback and removal | UNVERIFIED | Need actual user-facing flows and retention of unrelated host settings and research outputs. |
| Jobs, deduplication and recovery | PARTIAL | Durable job records, locks, a ten-job active queue bound, cancellation flags and receipt reconciliation are implemented. A cancellation request is not proof MATLAB stopped. Timeout/quarantine behavior and late results need native lifecycle acceptance. |
| Shared coordinator and retention | PARTIAL | Cross-process locks serialize native work for one runtime root. The planned shared IPC coordinator, warm reusable session, automatic retention UI and complete resource measurements remain open. |
| Published Alpha package | READY for distribution; end-user acceptance PARTIAL | [Windows Alpha](https://github.com/saigyujikingyo-png/matlab-companion/releases/tag/v0.1.0-alpha.1) is published. Fresh release download, published asset digest and checksum match the tested archive. Signature/warning behavior and complete end-user release gates remain separate. |

The final package receipt records clean source at `c5c7317`, bundled Python 3.12.14,
and archive SHA-256
`8b22ed6b715f3f7ec4f474973db63d24612fc1ce27179e9ccdf62e9263a7ae2a`.
A focused byte scan found no exact local builder username or checkout path,
and no embedded builder metadata. That scan is not a comprehensive secret
audit. The package check did not open a visible GUI, change a host connection,
start MATLAB, download the vendor backend or establish new-device acceptance.

The [historical alpha.1 release checkpoint](STATUS.md#historical-alpha1-release-checkpoint) distinguishes this
immutable source/runtime and archive from later documentation-only receipt
updates. Earlier native, model and package receipts remain evidence for
their named commits and are not relabelled as final-archive checks.

No stable or end-user-ready claim is made. Keep native execution, portable
tests, cloud containers, installation, model behavior, visual review and
received-file evidence separate when updating this matrix.
