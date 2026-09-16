# Implementation status

Updated: 2026-09-16. Version: 0.1.0a3 released (R2 Windows early preview).

<a id="current-r2-candidate"></a>

## Current R2 release

The owner approved R2 on 2026-09-16. The release adds a per-root local job
coordinator, private JSON IPC, thin stdio frontends, factual job phases and event
sequences, bounded waiting, passive storage accounting and held-handle native
exit observation. R3 has not started. Native execution remains Windows-only;
unsupported native observation is rejected before a scientific job is admitted.
See [R2 durable jobs](R2_DURABLE_JOBS.md) for the current evidence ledger.
Alpha.3 is published and installed on the recorded current device. Alpha.2
remains the retained rollback baseline. Broader usability, host and saved-cloud
combinations remain explicit unverified limits of this preview.

### Immutable release identity

- Runtime/source: `1b2eb73bcd674056cf756260ee5359c083c24afe`.
- Windows archive: `MATLAB-Companion-0.1.0a3-windows-x64.zip`, 33,104,323 bytes.
- Archive SHA-256: `d6a839606570d94a83407b7d1276bd2068c72c260d03cda210f33c7841b30aaa`.
- Build identity is not package-runtime, native, model or publication acceptance.
  Later documentation and receipt commits do not change these archive bytes.

| Gate | State | Evidence / remaining work |
| --- | --- | --- |
| R2 implementation | IMPLEMENTED at the frozen runtime | Per-root coordinator, bounded private IPC, durable phase/sequence/wait, queue/storage observations and separate native-exit observation; six tools and five operations retained |
| Exact-source portable CI | PASSED for recorded scope | [CI 35083094659](https://github.com/saigyujikingyo-png/matlab-companion/actions/runs/35083094659), [receipt](../verification/ci-v0.1.0-alpha.3.json): Windows 364 passed, 6 skipped in 37.03 s; Ubuntu 363 passed, 7 skipped in 23.19 s. Both passed Ruff, 22 schemas, actual stdio and the 89-file public audit. Platform/host-restriction skips remain separate from positive process-lifetime evidence |
| Earlier source-native lifecycle checkpoint | HISTORICAL PASS at `de1cf61` | [Three-case receipt](../verification/native-r2-source-checkpoint.json): client disconnect, explicit cancellation, and coordinator crash/quarantine with sentinel preservation. This does not accept the final `1b2eb73` archive |
| Relocated final-package integrity and runtime | PASSED for recorded scope | [Package receipt](../verification/package-v0.1.0-alpha.3.json): 3,991 manifest entries, zero mismatches/unlisted files, pre/post-runtime hash readback, Python 3.12.14. Self-test 2.234 s; actual stdio and withdrawn Tk 4.437 s. Isolated prestarted coordinator exited idle; zero jobs/dispatches. Focused builder-path scan found zero matches; not a comprehensive secret audit |
| Exact-package native lifecycle | PASSED for three recorded cases | [R2 receipt](../verification/native-r2-v0.1.0-alpha.3.json): prestarted-coordinator client disconnect, explicit cancellation and crash/quarantine, with one native entry per case and preserved synthetic sentinel. Crash exit was independently observed through a held handle; the interrupted production observer remained unconfirmed and unknown/quarantine stayed intact |
| Exact-package native science and local delivery | PASSED for six recorded cases | [Scientific receipt](../verification/native-v0.1.0-alpha.3.json): all five operations on MATLAB R2026a Update 5, 43 original-file readbacks, applicable native reopen/numerical/script checks, and six held-handle-confirmed native exits. Imported runtime hashes match the clean immutable package manifest |
| Representative Codex model and original delivery | PASSED AFTER CORRECTION; first attempt failed | [Combined receipt](../verification/codex-r2-v0.1.0-alpha.3.json): three actual turns, 14 MCP calls, one scientific job/dispatch, three valid waits and seven verified original local files. One delivery omitted `job_id` and was rejected; a delivery-only turn reused the completed job. Requested Terra max; resolved model/effort metadata is unavailable |
| Current-device upgrade and registered host | PASSED for recorded scope | [Upgrade receipt](../verification/local-upgrade-v0.1.0-alpha.3.json): 3,991 manifest files, official Codex connection, enabled plugin cache, selected-root Start-menu target and backups verified. Settings/jobs, retained alpha.2 files and seven other MCP connections preserved. Registered read-only probe validated six schemas/calls and ten resources; no coordinator or native dispatch started |
| Saved cloud development container | UNVERIFIED for alpha.3 | Successful Ubuntu CI is separate from a saved-container check and remote MATLAB execution; this broader combination is outside the accepted preview scope |
| GitHub publication and fresh-download integrity | PASSED | [Alpha.3 release](https://github.com/saigyujikingyo-png/matlab-companion/releases/tag/v0.1.0-alpha.3), [publication receipt](../verification/release-v0.1.0-alpha.3.json): tag resolves to `1b2eb73`; published asset digest, fresh 33,104,323-byte ZIP and downloaded checksum match the accepted SHA-256 |
| Visible wizard, fresh device and other hosts | UNVERIFIED | No result above establishes these broader end-user gates |

The source-native checkpoint, package checks, installed command and model route
keep separate identities and scopes. An explicitly prestarted coordinator does
not establish automatic startup under a host that refuses process breakaway.
R3 delivery changes and later roadmap items remain unstarted proposals.

The [first model preparation attempt](../verification/codex-r2-first-preparation.json)
failed an operator-side canonical-path comparison before invoking Codex: zero
scientific jobs and dispatches. Independent observation confirmed an empty ready
coordinator; the failed helper had not returned its handle. Only the ignored
operator's private-root normalization changed. This preparation failure was not
a model retry or replay of a scientific write.

The [first actual model turn](../verification/codex-r2-first-model-attempt.json)
then stopped safely because the operator had disabled the code-mode host needed
by Codex's tool router. It made no Companion calls, jobs or dispatches. Its
32.188-second turn consumed 18,005 input tokens (7,936 cached), 1,302 output
tokens (1,113 reasoning); these are reported counters, not a cost estimate.
Only that operator override was removed for the second actual turn. That turn
completed one 41-point kinetics job and three valid sequence-aware waits, then
omitted `job_id` from its first delivery request (`INPUT_INVALID`, no bytes
copied). The third turn explicitly delivered the seven originals from the same
completed job. Protected job records and original bytes remained unchanged.
The [combined receipt](../verification/codex-r2-v0.1.0-alpha.3.json) records
`passed_after_correction`, with first-attempt success false.

All three actual model turns total 191.688 seconds and 14 MCP calls: one run,
three waits and ten artifact calls, including the rejected delivery. Actual
counters total 277,722 input (213,504 cached), 7,236 output (4,301 reasoning)
tokens; overlapping categories are not added together. The zero-model
preparation adds 1.781 seconds separately. CLI configuration requested
`gpt-5.6-terra` / `max`; resolved model/effort metadata was absent and remains
unconfirmed. No cost or efficiency saving is inferred. The argument error
remains a model-usability gap; R3 is still an unstarted proposal.

## Historical R1 acceptance

The owner approved R1. Passive diagnostics, selected-root propagation, durable
execution isolation/process identity and over-limit local-delivery routing are
implemented. The integrated portable suite passed 215 tests, Ruff, 22 schemas,
real stdio and the public audit. Exact runtime `41f9cf7` passed Windows/Ubuntu CI,
the bounded native interruption/sentinel case, and final-package six-case native
acceptance covering all five operations with 43 original-file readbacks.
The clean 33,054,016-byte package has 3,976 verified manifest entries.
See [R1 reliability](R1_RELIABILITY.md) for receipts and the retained first-probe
failure. At that alpha.2 checkpoint R2/R3 had not started; R2 is now implemented
in the separately identified release above. New model, visible setup,
new-device and saved cloud-container acceptance remain separate.

[Alpha.2 is published](https://github.com/saigyujikingyo-png/matlab-companion/releases/tag/v0.1.0-alpha.2);
its GitHub asset digest, fresh ZIP download and checksum match the accepted
archive ([publication receipt](../verification/release-v0.1.0-alpha.2.json)).
The [current-device upgrade](../verification/local-upgrade-v0.1.0-alpha.2.json)
passed official Codex connection readback, enabled plugin-cache verification,
Start-menu target readback and read-only MCP status/help/resource checks through
the registered command. Settings, existing jobs, retained alpha.1 files and
pre-existing other MCP entries were preserved. The previous connection,
plugin files and shortcut were backed up. Downgrade/removal were not exercised.

## Historical alpha.1 acceptance

Later same-day update: the icon and current-device installation are complete;
see [installation receipt](../verification/local-installation-2026-09-15.json).
An installed MCP client completed a separate kinetics case and seven-file local
readback. A prior probe interruption is preserved separately. The
[alpha review](ALPHA_REVIEW_2026-09-15.md) identifies reliability and delivery
gaps. At that historical checkpoint, the [technical route](NEXT_TECHNICAL_ROUTE.md)
was awaiting owner approval and next-stage code had not started.

Final source/runtime checkpoint:
`c5c73174f3507f5291df5fbcea28a67795ea0763`.
Its CI, saved cloud container, final archive runtime checks and native
execution from that exact relocated archive passed. The earlier
source-native pass at `6ac645d` remains historical. The complete model-driven
calibration/edit/local-delivery workflow passed after corrections at
`cf4a705`; the focused revision passed at `6ac645d`. Visible setup, a new
user/device, upgrades and other-host acceptance remain separate gates.

| Gate | State | Evidence / remaining work |
| --- | --- | --- |
| Host-neutral core | READY for bounded preview | Six tools, five operations, durable jobs and validated contracts |
| Portable correctness | READY at final source checkpoint | [CI run 35003649768](https://github.com/saigyujikingyo-png/matlab-companion/actions/runs/35003649768) at `c5c7317`: Windows 164 passed in 8.01 s; Ubuntu 163 passed, one Windows-only CLI test skipped, in 3.86 s. Ruff, 22 schemas, real stdio and 44-file public audit passed on both runners |
| MCP protocol | READY for programmatic clients | Source CI and the relocated bundle exercised real stdio discovery, calls, schema resources and structured JSON fallback; target-host model acceptance remains separate |
| Native MATLAB source checkpoint | READY for historical recorded cases | [Earlier native checkpoint](../verification/native-release.json): six cases cover five operations at `6ac645d`, Windows 11, Python 3.12.14, backend 0.13.0 and MATLAB R2026a Update 5; retained separately from the final archive result |
| Final archive native execution | READY for recorded cases | [Final native receipt](../verification/native-v0.1.0-alpha.1.json) binds `c5c7317` and the final archive SHA-256 to execution from the relocated Windows release runtime: six cases cover all five operations, with local byte/hash delivery readback; profile has native reopen, and the other operations also pass numerical checks and script rerun |
| Local file delivery | READY for observed cases | Original bytes, size and SHA-256 readback; host attachments unverified |
| Windows bundle | READY for final archive runtime scope | [Final package receipt](../verification/package-v0.1.0-alpha.1.json): clean `c5c7317` source, 33,013,051 bytes, 3,963 manifest entries, zero mismatches/unlisted files; relocated bundled-runtime protocol and hidden Tk checks passed. Native acceptance is a separate row |
| Current-device installation and icon | READY for recorded scope | Original package files verified; named Codex connection and enabled personal plugin read back; PNG/ICO hashes match installed assets; Start-menu shortcut recorded. Installed kinetics, native reopening/rerun and seven-file local readback passed. This is not a new model or visible-wizard acceptance |
| Visible setup and installation lifecycle | UNVERIFIED | Visible wizard, new user/device, upgrade, repeated installation, recovery and removal need actual acceptance |
| Codex model workflow | READY for recorded cases after corrections | [Complete workflow](../verification/codex-benchmark.json) at `cf4a705`: 66 calls, 14 rejected calls, calibration and revision passed, all 16 requested local files read back. [Focused revision](../verification/codex-revision-release.json) at `6ac645d`: 8 calls, 1 run request, zero errors and native preservation/reopen/rerun passed |
| Model efficiency | PARTIAL | Complete workflow was not a first-attempt success and loaded unrelated plugins. The focused revision has a different scope; its lower call count does not establish whole-workflow savings |
| Other hosts | PARTIAL | ChatGPT Chat, local/cloud Work, Claude and WorkBuddy require independent acceptance |
| Cloud environment | READY at final source checkpoint | [Cloud receipt](../verification/cloud-environment.md): restarted Linux universal container at `c5c7317`, Python 3.12.13, setup/maintenance, 163 tests passed and one Windows-only CLI test skipped in 7.64 s; Ruff, 22 schemas, real stdio and 44-file public audit passed. Earlier runs remain historical |
| Figure visual checks | READY for selected exports | Assistant visual inspection of the TSV calibration and light-style kinetics exports completed; this is not a visible MATLAB editing or complete figure-quality acceptance |
| Stable release acceptance | PARTIAL | Alpha preview only; clean-device, upgrade, owner review and broader host gates open |

The architecture document is an approved design record, not a list of shipped features. R2 adds private local IPC. Warm sessions, remote authentication/service and host attachment adapters are not implemented.

The alpha.1 source review identified two P1 reliability concerns: CLI diagnostics
can resume an orphaned queue during core construction, and failure quarantine
is published after execution-lock release, creating a potential cross-coordinator
dispatch window. Custom-root propagation and over-limit resource routing also
needed correction. R1 repairs are tracked separately above; the historical
installed default-root case did not fix or certify them. See the review for
its original evidence and confidence levels.

## Historical alpha.1 release checkpoint

The final Windows archive records clean source/runtime commit
`c5c73174f3507f5291df5fbcea28a67795ea0763` and Python 3.12.14. Its SHA-256 is
`8b22ed6b715f3f7ec4f474973db63d24612fc1ce27179e9ccdf62e9263a7ae2a`.
The [package receipt](../verification/package-v0.1.0-alpha.1.json) binds the
checks to those exact 33,013,051 bytes. Earlier package receipts, including
the [clean `6ac645d` checkpoint](../verification/package-clean-release.json),
remain historical.

[Windows Alpha release](https://github.com/saigyujikingyo-png/matlab-companion/releases/tag/v0.1.0-alpha.1)
is published with the ZIP, checksum and scoped acceptance receipts. A fresh
GitHub download matches the tested archive byte-for-byte; the asset digest
and downloaded checksum also match ([publication receipt](../verification/release-v0.1.0-alpha.1.json)).
Final-archive native acceptance passed for the recorded cases. Receipt and
documentation updates can be committed after the immutable build without
changing its recorded code or rebuilding its bytes; they do not silently
change the archive's source commit. Future code changes require a new build
and matching acceptance.

A focused
scan found no exact local builder username or checkout-path bytes and no
embedded builder metadata; it is not a comprehensive secret audit. Hidden
Tk 8.6.12 construction/update/destruction passed with the window withdrawn.
This package check did not change host configuration, launch MATLAB,
download the vendor backend or establish fresh-device acceptance.

## Recovery and privacy

Jobs, input snapshots, native logs and results stay in local application data. The official subprocess receives a small OS/licence environment, excluding model tokens. Diagnostics may contain local paths and scientific data; review them before sharing. Public checks use synthetic data.

Queued writes are idempotent. A coordinator disappearing after dispatch marks the outcome unknown and quarantines the executor. Reconcile the existing job before any retry. Cancellation is a request, not proof of exit. Setup recovery requires owner confirmation that the plugin-owned session stopped; it never kills unrelated MATLAB. Jobs and delivered files are retained for explicit review/removal; automatic pruning is not implemented.

## Historical alpha.1 measurements and current limits

The recorded alpha.1 final-archive synthetic jobs took about 11–23 seconds each including fresh MATLAB startup and verification on this machine. That relocated bundle's portable self-test took 1.907 seconds and protocol/hidden-Tk checks took 3.938 seconds. Its default output schemas were roughly 2.4–4.3 KB each. These historical observations do not measure alpha.3 performance or establish general token savings.

Both model records requested `gpt-5.6-terra` with `max` reasoning through an
ephemeral Codex CLI session. The complete run used the existing signed-in
account and included unrelated installed plugins; the focused revision
disabled those plugins. Recorded host token counters are:

| Run | Seconds | Input | Cached input | Output | Reasoning output |
| --- | ---: | ---: | ---: | ---: | ---: |
| Complete calibration/edit/delivery, `cf4a705` | 628.875 | 2,377,535 | 2,234,368 | 21,488 | 15,212 |
| Focused revision, `6ac645d` | 85.141 | 203,246 | 168,192 | 2,276 | 1,465 |

Cached input is a subset of input; reasoning output is a subset of output.
No billing cost or quota saving is inferred. The complete run's scoring
initially treated an optional profile as a required delivery; this was
corrected by reading existing jobs and bytes, without rerunning MATLAB or
the model. Its 14 rejected calls and first-attempt failure remain recorded.
The focused run validates revision behavior, not a replacement full delivery
or fresh-device benchmark.

CSV/TSV input limit: 256 MiB. Individual artifact limit: 512 MiB. Inline MCP bytes: 16 MiB; larger files currently require approved local delivery because the resource reader has the same 16 MiB limit. One coordinator accepts at most ten active jobs. Input/output directories must be selected in setup.
