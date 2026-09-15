# MATLAB Companion

An independent Chembridge plugin for reproducible MATLAB analysis, editable native artifacts and natural-language agent workflows. Ask an agent to inspect CSV/TSV data, plot XY data, fit a linear calibration, simulate first-order decay or revise a Companion-owned figure.

**0.1.0a1 is an early Windows preview.** Five bounded operations have run on licensed MATLAB R2026a Update 5. Portable, native, installation, model and host-delivery acceptance remain separate. See [current status](docs/STATUS.md) and [compatibility](docs/COMPATIBILITY.md). This project is not affiliated with MathWorks or the University of Edinburgh.

The [current alpha review](docs/ALPHA_REVIEW_2026-09-15.md) records open diagnostic,
recovery, configuration and large-file delivery issues. The
[next technical route](docs/NEXT_TECHNICAL_ROUTE.md) is a design awaiting approval.

Read [development principles](DEVELOPMENT_PRINCIPLES.md), [architecture](docs/ARCHITECTURE.md) and [implementation contract](docs/IMPLEMENTATION_CONTRACT.md). Native execution, portable checks, installation, model calls and host file delivery have separate evidence.

## Install and use

Download the [Windows Alpha package and checksum](https://github.com/saigyujikingyo-png/matlab-companion/releases/tag/v0.1.0-alpha.1).

Extract the Windows preview bundle to a local folder and open **Start Setup.vbs**. Select your MATLAB installation and permitted input/output folders, install or verify the official backend, and connect Codex. The bundle includes Python and dependencies; ordinary users do not need a source checkout or Python installation. Keep the extracted folder in place after connection.

MATLAB must already be installed and licensed. Setup downloads the pinned official MathWorks MCP backend and checks its SHA-256. Read [installation and recovery](docs/INSTALLATION.md) and [third-party notices](THIRD_PARTY_NOTICES.md).

Example requests:

- “Plot concentration against absorbance from my selected CSV and save an editable figure.”
- “Fit a free-intercept calibration with this column as relative weights. Include units and standard errors.”
- “Simulate first-order decay at 0.25 per second, starting at 2 mmol/L, up to 8 seconds.”

Original input bytes are retained. Non-profile workflows deliver a standalone `.m` script, `.mat`, `.fig`, CSV, PNG, PDF and method metadata as applicable, with native reopen and script rerun checks. Profiling has native MAT readback but does not generate or claim a standalone script rerun.

## Interface

One core exposes six tools: `matlab_status`, `matlab_help`, `matlab_inspect`, `matlab_run`, `matlab_job` and `matlab_artifacts`. Every tool has a validated output schema, compact structured results and consistent JSON metadata fallback. Operation schemas are discovered on demand. Media stays in content/resource blocks. See [contracts](docs/CONTRACTS.md).

The preview uses local stdio and one owned MATLAB session per job. General MATLAB evaluation, third-party MAT/FIG loading, public remote service and host attachment adapters are outside this version. A resource URI does not establish host delivery; verified local delivery requires destination size/hash readback. Unknown outcomes are reconciled without automatic replay.

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

`uv run python scripts/native_acceptance.py` explicitly starts licensed local MATLAB. `uv run python scripts/build_windows_bundle.py` builds the preview with a clean CPython 3.12 runtime and locked production dependencies. Package version is `0.1.0a1`; the optional Codex guidance adapter uses semantic version `0.1.0-alpha.1`. It uses the MCP connection created by setup and is not another execution core.

[Cloud environment receipt](verification/cloud-environment.md) · [MIT source licence](LICENSE)
