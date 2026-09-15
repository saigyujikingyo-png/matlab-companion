# Implementation status

Updated: 2026-09-15. Version: 0.1.0a1 (early preview).

Current implementation checkpoint:
`cf4a705f564a8dc1c0174de4b1ad812838245614`.
Native recipes, Windows/Ubuntu CI, the Windows bundle after path relocation,
and the matching Codex cloud container have passed their recorded checks.
Visible setup, a new user/device, upgrades and host/model acceptance remain
separate gates. A model evaluation is in progress; no result is claimed yet.

| Gate | State | Evidence / remaining work |
| --- | --- | --- |
| Host-neutral core | READY for bounded preview | Six tools, five operations, durable jobs and validated contracts |
| Portable correctness | READY at recorded commit | [CI run 35000493121](https://github.com/saigyujikingyo-png/matlab-companion/actions/runs/35000493121) succeeded on Windows and Ubuntu at `cf4a705`; tests, Ruff, contracts, stdio smoke and public-file audit passed |
| MCP protocol | READY for programmatic clients | Source CI and the relocated bundle exercised real stdio discovery, calls, schema resources and structured JSON fallback; target-host model acceptance remains separate |
| Native MATLAB | READY for recorded synthetic cases | [Native checkpoint](../verification/native-final.json): six cases cover five operations at `cf4a705`, Windows 11, Python 3.12.14, backend 0.13.0 and MATLAB R2026a Update 5; other builds/devices remain unverified |
| Local file delivery | READY for observed cases | Original bytes, size and SHA-256 readback; host attachments unverified |
| Windows bundle | READY for relocation/runtime scope | [Package checkpoint](../verification/package-final.json): 32,994,484-byte archive, 3,955 manifest entries, zero mismatches/unlisted files, bundled-runtime protocol and hidden Tk checks passed after moving to a path with spaces and Chinese characters |
| Visible setup and installation lifecycle | UNVERIFIED | Visible wizard, new user/device, upgrade, repeated installation, recovery and removal need actual acceptance |
| Codex model workflow | IN PROGRESS | Evaluation has started; a passing protocol or native run is not its result |
| Other hosts | PARTIAL | ChatGPT Chat, local/cloud Work, Claude and WorkBuddy require independent acceptance |
| Cloud environment | READY at recorded commit | [Cloud receipt](../verification/cloud-environment.md): new Linux universal container at `cf4a705`, Python 3.12.13, setup/maintenance, 163 tests in 5.66 s, Ruff, 22 schemas, real stdio and 36-file public audit passed; earlier `f3e1e67` results retained |
| Figure visual checks | READY for selected exports | Assistant visual inspection of the TSV calibration and light-style kinetics exports completed; this is not a visible MATLAB editing or complete figure-quality acceptance |
| Stable release acceptance | PARTIAL | Alpha preview only; clean-device, upgrade, owner review and broader host gates open |

The architecture document is an approved design record, not a list of shipped features. Warm sessions, shared IPC, remote authentication/service and host attachment adapters are not implemented.

The verified Windows archive SHA-256 is
`a5f88345e3f5249697bbf5e483c675452e837a3ab5480936c6c042d4c5ecb698`.
Its manifest records clean source at `cf4a705` and Python 3.12.14. A focused
scan found no exact local builder username or checkout-path bytes and no
embedded builder metadata; it is not a comprehensive secret audit. Hidden
Tk 8.6.12 construction/update/destruction passed with the window withdrawn.
This package check did not change host configuration, launch MATLAB,
download the vendor backend or establish fresh-device acceptance.

## Recovery and privacy

Jobs, input snapshots, native logs and results stay in local application data. The official subprocess receives a small OS/licence environment, excluding model tokens. Diagnostics may contain local paths and scientific data; review them before sharing. Public checks use synthetic data.

Queued writes are idempotent. A coordinator disappearing after dispatch marks the outcome unknown and quarantines the executor. Reconcile the existing job before any retry. Cancellation is a request, not proof of exit. Setup recovery requires owner confirmation that the plugin-owned session stopped; it never kills unrelated MATLAB. Jobs and delivered files are retained for explicit review/removal; automatic pruning is not implemented.

## Measurements and limits

The recorded `cf4a705` synthetic jobs took about 12–24 seconds each including fresh MATLAB startup and verification on this machine. The relocated bundle's portable self-test took 3.625 seconds and protocol/hidden-Tk checks took 5.032 seconds. Default output schemas are roughly 2.4–4.3 KB each. These observations do not establish general performance or token savings. Actual model usage is reported only when supplied by the host.

CSV/TSV input limit: 256 MiB. Individual artifact limit: 512 MiB. Inline MCP bytes: 16 MiB; larger files use resource/local delivery. One coordinator accepts at most ten active jobs. Input/output directories must be selected in setup.
