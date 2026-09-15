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
| `matlab_status` | Backend observation and up to 50 capability observations. `unavailable`, `unsupported` and `unverified` states require reasons; passive discovery is not licensed MATLAB execution. |
| `matlab_help` | Up to five operation descriptions, input requirement and parameter/result schema references; optional pagination cursor. |
| `matlab_inspect` | Input identity, filename, media type, byte count, SHA-256, trust classification and optional typed CSV profile. |
| `matlab_run` | Stable accepted job identity, state and bounded summary. Accepted scientific work is asynchronous. |
| `matlab_job` | Job state, metrics, verification flags, artifact count and error, plus a result reference only for the matching completed operation. |
| `matlab_artifacts` | Up to 100 original artifact metadata records, optional independent delivery receipt and pagination cursor. File bytes and large JSON results remain content/resource blocks. |

Job states are `queued`, `running`, `cancel_requested`, `completed`, `cancelled`, `failed`, `interrupted` and `unknown`. Failed, interrupted and unknown jobs require explanatory errors. A cancel request can observe a job that has already completed; it must preserve that observed result rather than invent cancellation.

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
| `matlab_job.status`, `.cancel`, `.reconcile` | Shared job lifecycle model. The action determines core behavior; the response preserves the actual observed state, including terminal-state races. |
| `matlab_artifacts.list` | Bounded artifact metadata. |
| `matlab_artifacts.read` | Successful reads identify exactly one original artifact. |
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

## Coverage ledger

Current contributor verification: `uv run pytest -q tests/test_contracts.py` — **122 passed**; `uv run ruff check src/matlab_companion/contracts.py tests/test_contracts.py` — passed. These are portable fixtures, not licensed MATLAB execution or host acceptance. The root integration suite owns real server invocation, adapter integration and current full-checkout evidence.

| Area | Implemented and verified here | Separate/pending evidence |
| --- | --- | --- |
| Six public tool models | Per-tool success/error, schema validity, strict shape, canonical text fallback and known job-ID retention | Actual MCP invocation and each host's discovery/rendering |
| Five scientific operations | Per-operation parameter/result/native receipt fixtures; wrong operation dispatch rejected | Native numbers, native reopening, standalone script rerun and figure quality |
| Eight dispatcher routes | Per-route success/error schema checks; missing read identity/delivery evidence rejected | Server dispatch and original content transfer |
| Lifecycle/errors | Public queued/running/cancel-requested/completed/cancelled/failed/interrupted/unknown; native terminal states and malformed combinations | Real cancellation, process loss and late-receipt recovery |
| Scientific nulls and units | Nonfinite/type coercion rejection, disjoint missing counts, uncertainty/R-squared nulls, composite unit preservation | Numerical correctness across additional methods/data/toolboxes |
| Artifacts/delivery | Filename/hash/size/media constraints, same-job binding, resource-versus-delivery distinction | Actual size/hash readback and host attachment acceptance |
| Compatibility/efficiency | Compact separate registries and bounded defaults; individual default output schemas below the portable 12 KB ceiling | Terra max benchmark, measured tokens/cost, real host schema dialects and end-to-end latency |

Keep this ledger aligned with changed models and route behavior. A new native operation or artifact dispatcher needs a typed result and focused failure checks before interface completion is claimed.
