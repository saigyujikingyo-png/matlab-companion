# Output contracts

Contract version: **1.0**. The source of truth is [`contracts.py`](../src/matlab_companion/contracts.py), using the locked Pydantic version. Public JSON Schemas are generated from those same models. Schema validation and native scientific acceptance are separate checks.

## Public tool responses

Each of the six tools has an object output schema, rejects undeclared fields, and validates its result before delivery. The shared fields are:

| Field | Meaning |
| --- | --- |
| `contract_version` | Literal `1.0`; incompatible field meanings require a new contract version. |
| `request_id` | UUID text identifying this tool invocation. |
| `operation` | The exact public tool name. A scientific job's operation is recorded separately in `job.operation`. |
| `observed_at` | An actual UTC ISO timestamp, using `Z` or `+00:00`. Invalid calendar dates are rejected. |
| `ok` | Whether the tool invocation succeeded. This is true exactly when the outer `error` is null. |
| `job_id` | UUID text or null. Once a job is known, the core preserves it on later failures. It must match any nested job summary. |
| `error` | Null, or a bounded `{code, message, retryable, recovery}` object. Codes use stable upper-case identifiers defined by the core. Retry defaults to false. Recovery text does not authorise an automatic repeated write. |

Models materialise their documented defaults during validation. Required scientific values cannot be omitted; explicitly nullable values remain null in both `structuredContent` and the canonical serialized JSON text fallback. A passive query can succeed while reporting a failed job or unavailable MATLAB installation. In that case `ok` remains true and the failure is in the nested job/backend state. Direct operation failures have `ok: false` and require MCP `isError: true` in the server adapter.

| Tool | Additional typed response |
| --- | --- |
| `matlab_status` | Backend observation, up to 50 capability observations and an optional typed `runtime` accounting snapshot. `unavailable`, `unsupported` and `unverified` states require reasons; passive discovery is not licensed MATLAB execution. |
| `matlab_help` | Up to five operation descriptions, input requirement and parameter/result schema references; optional pagination cursor. |
| `matlab_inspect` | Input identity, filename, media type, byte count, SHA-256, trust classification and optional typed CSV profile. |
| `matlab_run` | Stable accepted job identity, state and bounded summary. Accepted scientific work is asynchronous. |
| `matlab_job` | Nested job state, factual phase, event sequence, metrics, verification flags, artifact count and error, plus a result reference only for the matching completed operation. Status and bounded wait use this same envelope. |
| `matlab_artifacts` | Up to 100 original artifact metadata records, optional independent delivery receipt and pagination cursor. File bytes and large JSON results remain content/resource blocks. |

Job states are `queued`, `running`, `cancel_requested`, `completed`, `cancelled`, `failed`, `interrupted` and `unknown`. Failed, interrupted and unknown jobs require explanatory errors. A cancel request can observe a job that has already completed; it must preserve that observed result rather than invent cancellation.

### Factual phase and event sequence

`job.phase` is nullable, with default null for older saved jobs whose phase was not recorded. Known phases are `queued`, `executing`, `validating`, `cancel_requested`, `completed`, `cancelled`, `failed`, `interrupted` and `unknown`. `executing` includes backend/session startup and the owned call; it does not claim that MATLAB has already started computing. `validating` records receipt/artifact validation, not successful native completion. It may accompany `running`, `cancel_requested`, `interrupted` or `unknown`. Other known phases match the state, with `running` represented by `executing`. No phase or state establishes that a native process has stopped. There are no estimated percentages or invented work totals.

`job.event_seq` is a strict integer from 0 through `9007199254740991`, the largest exactly representable JSON integer across common host runtimes. Missing values in older jobs default to 0; passive reads do not rewrite those saved jobs. Newly accepted jobs start at 1. The producer must increment the persisted value under the job-state lock only when the public job summary actually changes. Reads, repeated no-op cancellation, rejected state transitions and unchanged reconciliation do not increment it. A cursor belongs to one immutable job ID, remains monotonic across coordinator restarts and must never wrap or reset. A single response validator checks the cursor's shape; producer/consumer tests must establish this ordering across responses.

### Bounded observation through `matlab_job`

`action="wait"` adds observation to the existing job dispatcher. It accepts:

| Parameter | Meaning |
| --- | --- |
| `after_event_seq` | Optional nullable strict integer with the same bounds as `job.event_seq`. Null or omitted takes the first observed sequence as the baseline. |
| `timeout_seconds` | Finite JSON number from 0 through 10, default 5. Integers are accepted; strings, booleans and nonfinite numbers are rejected. |

These parameters are meaningful only for `wait`; explicitly supplying them to another action is rejected. An already newer sequence returns immediately. An ahead-of-store cursor is an `INPUT_INVALID` invocation error retaining the known job ID. States outside `queued`, `running` and `cancel_requested` return immediately, including `unknown` and `interrupted` requiring recovery. Otherwise, the call returns the current snapshot when the sequence changes or the deadline expires. A deadline is a successful observation, not a failed or cancelled scientific job. Timeout zero is an immediate snapshot.

The response keeps `job_id`, the nested `job`, and the existing optional `result`; there is no new result wrapper. Consumers compare the returned sequence and state, then use a later bounded wait if needed. Waiting does not reconcile, replay, cancel or take execution ownership. A client disconnect abandons its wait and leaves the scientific job alone. Installed multi-client and lifecycle tests are separate from the typed response checks.

### Queue and retained-storage accounting

`matlab_status.runtime` defaults to null when no accounting observation was supplied. A supplied snapshot has these fields:

| Field | Meaning |
| --- | --- |
| `max_active_jobs` | Integer literal 10: the admission limit includes queued, running and cancel-requested jobs. It is not ten queued jobs plus a running job. |
| `active_jobs` | Nonnegative integer or null. A complete snapshot requires a count no greater than `retained_jobs`; an incomplete snapshot requires null. Unknown jobs remain subject to the independent quarantine barrier. |
| `retained_jobs` | Nonnegative integer count of observed retained job directories. Incomplete accounting reports only the observed lower bound. |
| `storage_bytes` | Integer from 0 through `9007199254740991`: observed logical regular-file bytes under the resolved installation root's `jobs` directory. Incomplete accounting reports a lower bound, not a complete total. |
| `storage_complete` | Whether the bounded traversal and job-state observations completed without omissions. It does not promise an atomic filesystem snapshot. |
| `retention` | Literal `explicit_removal_only`. Scientific originals and unknown-job evidence do not expire automatically. This policy is not an implemented removal action. |
| `automatic_cleanup` | Boolean literal false. No retention timer deletes jobs or artifacts. |
| `observed_at` | Valid UTC observation timestamp for this accounting snapshot. |

Accounting reads bounded, small job-state JSON to classify jobs; scientific file contents are not read. Other retained files are counted by size, including staged inputs, outputs, receipts and recovery evidence. Symlinks are not followed. The traversal has a time budget and a 10,000-entry bound; reaching either bound, encountering an unreadable entry or failing to classify a job makes it incomplete. Installed runtimes/backends, approved input source folders and copies delivered outside the job store are outside this scope. Logical bytes are not allocated disk space, free disk space, a storage quota or authority to delete anything. The queue limit and executor quarantine remain enforced by the producer, not by this observational snapshot.

## Scientific operation registry

`operation_schemas()` returns `{operation: {contract_version, parameters, result}}`. Each parameter and result entry is its own generated JSON Schema. `validate_parameters(operation, object)` returns a normalized JSON-compatible object with defaults. `validate_operation_result(operation, object)` returns a validated operation-specific model. Unknown operations are rejected.

| Operation | Input contract | Result contract and meaningful checks |
| --- | --- | --- |
| `data_profile` | No parameters. | Rows and bounded named column profiles. Numeric finite, missing (NaN) and nonfinite (Inf) counts are disjoint and sum to rows. Text columns report only applicable counts. No finite numeric values means null extrema; finite values require ordered extrema. |
| `plot_xy` | Named x/y columns, explicit units and optional title. | Row count, original column names and units. This metadata is separate from the original editable figure and numerical preservation evidence. |
| `linear_calibration` | Plot fields, free or fixed-zero intercept, optional positive weight/sigma column and `relative`/`known_sigma` meaning. Known sigma requires a column. | Fit method, weight interpretation, degrees of freedom, slope/intercept, uncertainty, residual sums and R-squared. Degrees of freedom equal rows minus fitted parameter count. A fixed zero intercept stays zero. Missing uncertainty and undefined R-squared require null values and reasons. Relative-weight uncertainty cannot be calculated without residual degrees of freedom. |
| `first_order_kinetics` | Nonnegative initial concentration, finite positive rate/time, 2–10,000 points and explicit concentration/time units. | Solver tolerances, final concentration and analytic comparison error. A decay result cannot claim growth beyond its declared absolute tolerance. Scientific independent checks remain the core/native gate. |
| `revise_figure` | Core-resolved owned figure, nullable labels/title and nullable increasing finite limit pairs. | Changed labels and an actual boolean `curves_preserved: true`; false, numeric `1` and string `"true"` are rejected as successful preservation claims. Trust/path containment is enforced by the core before native opening. |

All numerical fields reject NaN, infinity, numeric strings and booleans. Counts require integers. No validator silently removes missing rows, converts physical units or manufactures values. Input/result units are nonempty strings up to 120 characters. Composite metric units allow 256 characters so two maximum-length input units can be preserved without truncation. A metric's null unit means unknown or not supplied, never an assumed dimensionless value; use explicit `"1"` for dimensionless quantities.

Metric values are finite numbers or null. `available` requires a value, including a legitimate zero, and a null unavailability reason. `unavailable` and `not_calculated` require a null value and nonempty reason. Fit-specific uncertainty availability is recorded separately from goodness of fit. Constant-response R-squared can be null with `r_squared_reason`; this is not reported as zero.

## Dispatch routes

`dispatch_schemas()` and `DISPATCH_OUTPUT_MODELS` expose route contracts without expanding the default tool catalog. `validate_dispatch_output(tool_name, action, payload)` applies the route-specific model before content delivery.

| Route | Response requirements |
| --- | --- |
| `matlab_job.status`, `.cancel`, `.reconcile`, `.wait` | Shared job lifecycle model. The action determines core behavior; the response preserves the actual observed state, including terminal-state races and successful wait deadlines. |
| `matlab_artifacts.list` | Bounded artifact metadata. |
| `matlab_artifacts.read` | Identifies exactly one original artifact. At or below 16 MiB the original bytes can accompany the response; above that limit `delivery` must be `not_delivered` / `local_copy`, with matching size/hash and an actionable reason. No unreadable ResourceLink is emitted. |
| `matlab_artifacts.deliver` | Successful delivery identifies one artifact and has a delivered/verified receipt; resource availability alone cannot pass. |
| `matlab_artifacts.read_result` | The known job identity is required; the scientific JSON content is separately validated by its operation model. |
| `matlab_artifacts.read_schema` | The generated registry supplies the JSON schema content. |

Inspection is currently one CSV registration/inspection operation, not a native-file dispatcher. The core rejects unsupported native MAT/FIG inputs. `host_attachment` is a reserved delivery method in the typed contract; its existence is not an implemented or accepted host adapter. The initial implementation supports authorised local copies and MCP original-resource reads.

## Native boundary

`validate_native_receipt(object)` validates a complete `NativeReceipt`. Its identity, observed UTC time, MATLAB version/release, summary, bounded metrics/artifacts and verification flags are required. Every completed receipt has a result model matching its declared scientific operation and a null error. Failed/cancelled receipts have null details and a bounded native error; a cancelled receipt requires `CANCELLED`, and a failed receipt cannot use that code. Partial artifact metadata can survive a failed run without becoming a success claim.

Native error codes are `INPUT_INVALID`, `NATIVE_EXECUTION_FAILED`, `NATIVE_VERIFY_FAILED` and `CANCELLED`. The core maps backend, validation, storage and lifecycle errors to public codes. Malformed receipts must be quarantined/reported against the original job, not returned as success or repaired by rerunning native work.

Native artifact names are ordinary relative filenames, with no separators, parent path, alternate stream or trailing Windows dot/space ambiguity. Roles are `original_input`, `native_data`, `native_figure`, `script`, `data_export`, `figure_export`, `method` and `preview`. Names and metric identifiers are unique within a receipt. The public artifact model adds the opaque artifact/job IDs, bytes, SHA-256, URI and verification state. The core separately checks containment, actual file bytes/hashes and ownership; a schema cannot establish these facts.

`native_reopen`, `numerical` and `script_rerun` are independent booleans. They describe performed checks, not installation, model compatibility or host receipt. The core must apply the operation's applicable acceptance checks and retain the underlying evidence before claiming verified output.

## Media, delivery and compatibility

Images, native files and large arrays remain original MCP content/resource blocks. The structured contract contains metadata, not duplicate base64 or full tables. A resource state of `available` means a resource can be requested; it does not mean a host downloaded it. `verified` delivery requires a destination reference, byte count and SHA-256. Actual destination readback is a separate adapter responsibility. Public responses reject unlisted delivery artifact IDs and artifacts from a different identified job.

The generated schemas use JSON Schema constructs supported by the current locked MCP SDK. The portable tests validate them with Draft 2020-12 and preserve equal JSON text fallback/structured values. Cross-field scientific/lifecycle invariants are also enforced by Pydantic model validators; schema consumers should not assume a generic JSON Schema validator performs those additional checks. No real host or model compatibility is implied by portable schema validation.

The R2 additions retain contract version 1.0, six tool names, existing field meanings and the nested job/result envelope. Older saved jobs and responses remain readable by the updated models through documented defaults. Consumers that pin an older schema with `additionalProperties: false` must refresh discovery before accepting the new optional fields; backward readability does not mean every frozen old schema accepts a newer response.

## Coverage ledger

Contributor verification commands are `uv run pytest -q tests/test_contracts.py` and `uv run ruff check src/matlab_companion/contracts.py tests/test_contracts.py`. These are portable fixtures, not licensed MATLAB execution or host acceptance. The root integration suite owns real server invocation, adapter integration and current full-checkout evidence.

| Area | Implemented and verified here | Separate/pending evidence |
| --- | --- | --- |
| Six public tool models | Per-tool success/error, schema validity, strict shape, canonical text fallback and known job-ID retention | Actual MCP invocation and each host's discovery/rendering |
| Five scientific operations | Per-operation parameter/result/native receipt fixtures; wrong operation dispatch rejected | Native numbers, native reopening, standalone script rerun and figure quality |
| Nine dispatcher routes | Per-route success/error schema checks; missing read identity/delivery evidence rejected; wait preserves the nested job/result envelope | Server dispatch, actual bounded waiting and original content transfer |
| Lifecycle/errors | Public queued/running/cancel-requested/completed/cancelled/failed/interrupted/unknown; factual phase consistency; legacy defaults and strict event cursors | Monotonic persistence across restarts, actual cancellation, client loss and late-receipt recovery |
| Runtime accounting | Complete versus incomplete counts, retained-byte bounds, literal retention policy and null legacy observations | Bounded filesystem traversal, simultaneous clients, queue admission and evidence retention |
| Scientific nulls and units | Nonfinite/type coercion rejection, disjoint missing counts, uncertainty/R-squared nulls, composite unit preservation | Numerical correctness across additional methods/data/toolboxes |
| Artifacts/delivery | Filename/hash/size/media constraints, same-job binding, resource-versus-delivery distinction | Actual size/hash readback and host attachment acceptance |
| Compatibility/efficiency | Compact separate registries and bounded defaults; individual default output schemas below the portable 12 KB ceiling | Terra max benchmark, measured tokens/cost, real host schema dialects and end-to-end latency |

Keep this ledger aligned with changed models and route behavior. A new native operation or artifact dispatcher needs a typed result and focused failure checks before interface completion is claimed.
