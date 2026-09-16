# MATLAB Companion

An independent Chembridge plugin for reproducible MATLAB analysis, editable native artifacts and natural-language agent workflows. Ask an agent to inspect CSV/TSV data, plot XY data, fit a linear calibration, simulate first-order decay or revise a Companion-owned figure.

**[0.1.0a3 / alpha.3 is released as the R2 Windows preview](https://github.com/saigyujikingyo-png/matlab-companion/releases/tag/v0.1.0-alpha.3).** Runtime `1b2eb73` passed Windows/Ubuntu CI, relocated package checks, three native lifecycle cases, six scientific cases with 43 original-file readbacks, and the current-device upgrade. The representative [model workflow passed after correction](verification/codex-r2-v0.1.0-alpha.3.json), with three model turns and seven original local files; first-attempt success is false.

R2 separates accepted jobs from individual agent clients and adds bounded waiting and factual progress. Saved cloud-container, visible-wizard, new-device and other-host acceptance remain unverified. R3 has not started. See the [release identity and evidence ledger](docs/STATUS.md#current-r2-candidate).

**0.1.0a2 remains the retained R1 rollback release.** Its historical results are kept separately from alpha.3 acceptance. See [current status](docs/STATUS.md) and [compatibility](docs/COMPATIBILITY.md). This project is not affiliated with MathWorks or the University of Edinburgh.

The [alpha review](docs/ALPHA_REVIEW_2026-09-15.md) records the original findings.
[R1 implementation and acceptance](docs/R1_RELIABILITY.md) tracks their repairs.
[R2 durable jobs](docs/R2_DURABLE_JOBS.md) tracks the current increment; the
[technical route](docs/NEXT_TECHNICAL_ROUTE.md) keeps R3 and later proposals separate.

Read [development principles](DEVELOPMENT_PRINCIPLES.md), [architecture](docs/ARCHITECTURE.md) and [implementation contract](docs/IMPLEMENTATION_CONTRACT.md). Native execution, portable checks, installation, model calls and host file delivery have separate evidence.

## Install and use

Download [Windows alpha.3 and its checksum](https://github.com/saigyujikingyo-png/matlab-companion/releases/tag/v0.1.0-alpha.3). The [publication receipt](verification/release-v0.1.0-alpha.3.json) confirms that the release tag, GitHub asset digest and fresh ZIP/checksum download match the tested archive.

Extract the Windows preview bundle to a local folder and open **Start Setup.vbs**. Select your MATLAB installation and permitted input/output folders, install or verify the official backend, and connect Codex. The bundle includes Python and dependencies; ordinary users do not need a source checkout or Python installation. Keep the extracted folder in place after connection.

MATLAB must already be installed and licensed. Setup downloads the pinned official MathWorks MCP backend and checks its SHA-256. Read [installation and recovery](docs/INSTALLATION.md) and [third-party notices](THIRD_PARTY_NOTICES.md).

Example requests:

- “Plot concentration against absorbance from my selected CSV and save an editable figure.”
- “Fit a free-intercept calibration with this column as relative weights. Include units and standard errors.”
- “Simulate first-order decay at 0.25 per second, starting at 2 mmol/L, up to 8 seconds.”

Original input bytes are retained. Non-profile workflows produce a standalone `.m` script, `.mat`, `.fig`, CSV, PNG, PDF and method metadata as applicable, with native reopen and script rerun checks. Profiling has native MAT readback but does not generate or claim a standalone script rerun.

## Interface

One core exposes six tools: `matlab_status`, `matlab_help`, `matlab_inspect`, `matlab_run`, `matlab_job` and `matlab_artifacts`. Every tool has a validated output schema, compact structured results and consistent JSON metadata fallback. Operation schemas are discovered on demand. Media stays in content/resource blocks. See [contracts](docs/CONTRACTS.md).

The alpha.3 release uses local stdio front ends and one on-demand coordinator per user and resolved installation root. The coordinator owns the durable queue and one fresh, owned MATLAB session per job. General MATLAB evaluation, third-party MAT/FIG loading, public remote service and host attachment adapters are outside this version. A resource URI does not establish host delivery; verified local delivery requires destination size/hash readback. Unknown outcomes are reconciled without automatic replay.

### Observe and recover jobs in alpha.3

Read state from `result.job.state`. `job.phase` reports observed work such as `queued`, `executing` or `validating`; it is not a percentage or proof that MATLAB stopped. `job.event_seq` increases when the persisted job summary changes. Older jobs may have a null phase and sequence zero without any diagnostic rewrite.

Use `matlab_job` with `action="wait"`, the same `job_id`, and `after_event_seq` set to the last observed sequence. `timeout_seconds` is 0–10 seconds, default 5. This bounds waiting inside the core after the request is received; service startup, IPC and host transport can add time. A deadline returns the current snapshot successfully. It does not cancel or fail the job.

Closing an agent client abandons its response or wait. It does not cancel accepted work. Reconnect to the same installation root and retain the job ID and original idempotency key; a lost response never triggers an automatic write retry. Cancellation requires an explicit `matlab_job` action, and `cancel_requested` does not mean the native session has stopped.

If a Windows host refuses independent process startup, open **Start Setup.vbs** from the installed bundle and explicitly choose **Start job service**, then return to the agent. The launcher reports the failure and does not fall back to a client-owned child. Starting this service can resume accepted, undispatched work; setup checks themselves remain passive. This design covers an individual client disconnect, not closure of the outer host, its Windows Job Object, or the operating system. Coordinator loss retains the R1 unknown/quarantine recovery boundary. Native process exit needs its own lifecycle evidence, separate from a backend return or idle service exit.

`matlab_status` observes retained job storage without starting workers or deleting files. When `storage_complete` is false, `retained_jobs` and `storage_bytes` are observed lower bounds and `active_jobs` is unknown (`null`). Counts cover logical files in the job store, not all installed/runtime or delivered files, available disk space or a quota. Originals and unknown-job evidence have no automatic expiry. The `explicit_removal_only` policy requires a separate authorized deletion; this release provides no job-removal action.

## Develop

Use Python 3.12 and the dependency lock. Portable checks need no MATLAB, licence, account or private data.

```sh
bash scripts/setup_codex_cloud.sh
uv run pytest -q
uv run ruff check src scripts tests
uv run python scripts/check_contracts.py
uv run python scripts/smoke_mcp.py
uv run python scripts/check_release.py
```

`uv run python scripts/native_acceptance.py` explicitly starts licensed local MATLAB. `uv run python scripts/build_windows_bundle.py` builds the preview with a clean CPython 3.12 runtime and locked production dependencies. The package version is `0.1.0a3` (`0.1.0-alpha.3` for release/adapter versioning). The optional Codex guidance adapter uses the MCP connection created by setup and is not another execution core.

[Cloud environment receipt](verification/cloud-environment.md) · [MIT source licence](LICENSE)
