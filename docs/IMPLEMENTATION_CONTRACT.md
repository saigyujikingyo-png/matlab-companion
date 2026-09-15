# Initial integration contract

Status: implemented integration boundary for the bounded alpha. Acceptance is recorded separately in `STATUS.md`. Public output contracts are defined in `contracts.py` and validated before delivery.

## Native request

The core writes a private `request.json` in an owned job directory. Fields: `contract_version` (`1.0`), `job_id` (UUID), `operation`, `input_path` (absolute staged CSV or null), `output_dir` (absolute owned outputs directory), `cancel_path` (absolute job-owned flag), `parameters` (the operation's validated object). Root owns request validation and staging. The packaged MATLAB entrypoint is `companion.execute(requestPath)`. Root supplies a fixed launcher to the upstream `run_matlab_file` tool; generated source contains only internally resolved, quoted paths. Native code never evaluates recipe strings as code.

Operations and parameters:

- `data_profile`: no parameters; numeric CSV columns and missing/nonfinite summary.
- `plot_xy`: `x_column`, `y_column`, `x_unit`, `y_unit`, `title` (default empty).
- `linear_calibration`: same fields plus `intercept` (`free` or `zero`, default free); `weights_column` (null or CSV column), `weights_kind` (`relative` or `known_sigma`, default relative). No inferred units or missing-row deletion.
- `first_order_kinetics`: `initial_concentration`, `rate_constant`, `time_end`, `points` (integer 2..10000), `concentration_unit`, `time_unit`, `title`. Finite positive rate/time; nonnegative initial concentration. No input required.
- `revise_figure`: `source_figure` (core-resolved trusted artifact path), `title`, `x_label`, `y_label` (nullable text); `x_limits`, `y_limits` (null or finite increasing pairs). Core supplies only an immutable artifact from its own job store; numeric curves are preserved.

## Native receipt

The helper writes `receipt.json` atomically at the job root (parent of output_dir), preserving `job_id`, including on caught failures. Fields:

- `contract_version`, `job_id`, `operation`, `state` (`completed`, `cancelled`, `failed`), `observed_at` (UTC ISO text), `matlab_version`, `matlab_release`.
- `summary` (bounded string), `metrics` (list of objects: `name`, `value` finite number or null, `unit`, `state` (`available`, `not_calculated`, `unavailable`), `method` text, `reason` nullable text).
- `artifacts` (list of objects: `name` relative filename only, `role`, `media_type`). Root verifies actual bytes and SHA-256 and emits public Artifact metadata.
- `verification`: `native_reopen`, `numerical`, `script_rerun` booleans. Only set true after actual corresponding checks.
- `details`: operation-specific result object; each operation has its own server-side model. Keep numerical outputs finite; unavailable values are null with explicit reason/availability.
- `error`: null or `{code, message}`. Never publish raw private stack traces.

Native code returns MAT, FIG, standalone M, CSV, PNG, PDF where applicable, and a method JSON. Output `.m` must run without private plugin paths. Reopen MAT/FIG and rerun the standalone M in an isolated function scope/output folder, preserving originals; root additionally checks numerical fixture expectations. `data_profile` need not claim figure/script verification; its applicable scope is explicit.

## Ownership

Root owns core, native backend Python integration, server, CLI, scripts, packaging, README and releases. The native contributor owns `matlab/` and its own `tests/test_native_source.py` only; do not launch MATLAB concurrently with root. The contracts contributor owns `src/matlab_companion/contracts.py`, `tests/test_contracts.py`, and `docs/CONTRACTS.md` only. The cloud contributor owns browser environment work and `verification/cloud-environment.md` only. Coordinate changes to this seam before implementation.
