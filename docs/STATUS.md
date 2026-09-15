# Implementation status

Updated: 2026-09-15. Version: 0.1.0a1 (early preview).

Recorded native, clean-package and focused model-revision checkpoint:
`6ac645d037992d1a565272f70f5e77815d69cc80`.
The complete model-driven calibration/edit/local-delivery workflow passed
after corrections at `cf4a705`; an updated focused revision passed at
`6ac645d`. CI and cloud results below retain their separately recorded
commits. These receipts do not certify later source changes or a later final
archive. Visible setup, a new user/device, upgrades and other-host acceptance
remain separate gates.

| Gate | State | Evidence / remaining work |
| --- | --- | --- |
| Host-neutral core | READY for bounded preview | Six tools, five operations, durable jobs and validated contracts |
| Portable correctness | READY at recorded commit | [CI run 35000493121](https://github.com/saigyujikingyo-png/matlab-companion/actions/runs/35000493121) succeeded on Windows and Ubuntu at `cf4a705`; tests, Ruff, contracts, stdio smoke and public-file audit passed |
| MCP protocol | READY for programmatic clients | Source CI and the relocated bundle exercised real stdio discovery, calls, schema resources and structured JSON fallback; target-host model acceptance remains separate |
| Native MATLAB | READY for recorded synthetic cases | [Native checkpoint](../verification/native-release.json): six cases cover five operations at `6ac645d`, Windows 11, Python 3.12.14, backend 0.13.0 and MATLAB R2026a Update 5; other builds/devices remain unverified |
| Local file delivery | READY for observed cases | Original bytes, size and SHA-256 readback; host attachments unverified |
| Windows bundle | READY for recorded checkpoint archive | [Clean-package checkpoint](../verification/package-clean-release.json): clean `6ac645d` source, 33,001,516-byte archive, 3,957 manifest entries, zero mismatches/unlisted files, bundled-runtime protocol and hidden Tk checks passed after moving to a path with spaces and Chinese characters. A later archive needs its own receipt |
| Visible setup and installation lifecycle | UNVERIFIED | Visible wizard, new user/device, upgrade, repeated installation, recovery and removal need actual acceptance |
| Codex model workflow | READY for recorded cases after corrections | [Complete workflow](../verification/codex-benchmark.json) at `cf4a705`: 66 calls, 14 rejected calls, calibration and revision passed, all 16 requested local files read back. [Focused revision](../verification/codex-revision-release.json) at `6ac645d`: 8 calls, 1 run request, zero errors and native preservation/reopen/rerun passed |
| Model efficiency | PARTIAL | Complete workflow was not a first-attempt success and loaded unrelated plugins. The focused revision has a different scope; its lower call count does not establish whole-workflow savings |
| Other hosts | PARTIAL | ChatGPT Chat, local/cloud Work, Claude and WorkBuddy require independent acceptance |
| Cloud environment | READY at historical recorded commit | [Cloud receipt](../verification/cloud-environment.md): Linux universal container at `cf4a705`, Python 3.12.13, setup/maintenance, 163 tests in 5.66 s, Ruff, 22 schemas, real stdio and 36-file public audit passed; earlier `f3e1e67` results retained. This does not certify `6ac645d` or later cloud source |
| Figure visual checks | READY for selected exports | Assistant visual inspection of the TSV calibration and light-style kinetics exports completed; this is not a visible MATLAB editing or complete figure-quality acceptance |
| Stable release acceptance | PARTIAL | Alpha preview only; clean-device, upgrade, owner review and broader host gates open |

The architecture document is an approved design record, not a list of shipped features. Warm sessions, shared IPC, remote authentication/service and host attachment adapters are not implemented.

The verified checkpoint Windows archive SHA-256 is
`b198e8417bd28dcaf9608990209dcb224a5cc42c2d0474f87b6f3ca440f4deb1`.
Its manifest records clean source at `6ac645d` and Python 3.12.14. A focused
scan found no exact local builder username or checkout-path bytes and no
embedded builder metadata; it is not a comprehensive secret audit. Hidden
Tk 8.6.12 construction/update/destruction passed with the window withdrawn.
This package check did not change host configuration, launch MATLAB,
download the vendor backend or establish fresh-device acceptance.

## Recovery and privacy

Jobs, input snapshots, native logs and results stay in local application data. The official subprocess receives a small OS/licence environment, excluding model tokens. Diagnostics may contain local paths and scientific data; review them before sharing. Public checks use synthetic data.

Queued writes are idempotent. A coordinator disappearing after dispatch marks the outcome unknown and quarantines the executor. Reconcile the existing job before any retry. Cancellation is a request, not proof of exit. Setup recovery requires owner confirmation that the plugin-owned session stopped; it never kills unrelated MATLAB. Jobs and delivered files are retained for explicit review/removal; automatic pruning is not implemented.

## Measurements and limits

The recorded `6ac645d` synthetic jobs took about 11–24 seconds each including fresh MATLAB startup and verification on this machine. The relocated checkpoint bundle's portable self-test took 2.172 seconds and protocol/hidden-Tk checks took 4.687 seconds. Default output schemas are roughly 2.4–4.3 KB each. These observations do not establish general performance or token savings.

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

CSV/TSV input limit: 256 MiB. Individual artifact limit: 512 MiB. Inline MCP bytes: 16 MiB; larger files use resource/local delivery. One coordinator accepts at most ten active jobs. Input/output directories must be selected in setup.
