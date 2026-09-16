"""Versioned, strict contracts shared by the native boundary and public MCP tools.

Large arrays and file bytes belong in artifacts, never in these bounded summaries.
The compact public job contract refers to separately validated operation results.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

CONTRACT_VERSION = "1.0"
MAX_INLINE_BYTES = 16 * 1024 * 1024
MAX_ACTIVE_JOBS = 10
MAX_EVENT_SEQ = 2**53 - 1
Identifier = Annotated[
    str, StringConstraints(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
]
JobId = Annotated[
    str,
    StringConstraints(
        pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    ),
]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Label = Annotated[str, StringConstraints(max_length=300)]
Unit = Annotated[str, StringConstraints(min_length=1, max_length=120)]
MetricUnit = Annotated[str, StringConstraints(min_length=1, max_length=256)]
Reason = Annotated[str, StringConstraints(min_length=1, max_length=1000)]
Summary = Annotated[str, StringConstraints(min_length=1, max_length=2000)]
FiniteNumber = Annotated[float, Field(allow_inf_nan=False)]
NonnegativeNumber = Annotated[FiniteNumber, Field(ge=0)]
PositiveNumber = Annotated[FiniteNumber, Field(gt=0)]
Count = Annotated[int, Field(ge=0, le=1_000_000_000)]
EventSequence = Annotated[int, Field(strict=True, ge=0, le=MAX_EVENT_SEQ)]
WaitSeconds = Annotated[float, Field(strict=True, ge=0, le=10, allow_inf_nan=False)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
Filename = Annotated[
    str, StringConstraints(min_length=1, max_length=255, pattern=r"^[^/\\\x00-\x1f]+$")
]
MediaType = Annotated[
    str,
    StringConstraints(
        min_length=3, max_length=120, pattern=r"^[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+$"
    ),
]
Uri = Annotated[
    str, StringConstraints(min_length=1, max_length=2048, pattern=r"^[A-Za-z][A-Za-z0-9+.-]*:")
]
Timestamp = Annotated[
    str,
    StringConstraints(
        min_length=20,
        max_length=40,
        pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|\+00:00)$",
    ),
]
Operation = Literal[
    "data_profile", "plot_xy", "linear_calibration", "first_order_kinetics", "revise_figure"
]
JobState = Literal[
    "queued",
    "running",
    "cancel_requested",
    "completed",
    "cancelled",
    "failed",
    "interrupted",
    "unknown",
]
JobPhase = Literal[
    "queued",
    "executing",
    "validating",
    "cancel_requested",
    "completed",
    "cancelled",
    "failed",
    "interrupted",
    "unknown",
]
ArtifactRole = Literal[
    "original_input",
    "native_data",
    "native_figure",
    "script",
    "data_export",
    "figure_export",
    "method",
    "preview",
]
Availability = Literal["available", "unavailable", "unsupported", "unverified"]


class ContractModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, allow_inf_nan=False, validate_default=True
    )


def _check_timestamp(value: str) -> None:
    """The regex is discoverable; parsing also rejects impossible calendar dates."""
    datetime.fromisoformat(value)


class NoParameters(ContractModel):
    pass


class PlotParameters(ContractModel):
    x_column: ShortText
    y_column: ShortText
    x_unit: Unit
    y_unit: Unit
    title: Label = ""


class LinearCalibrationParameters(PlotParameters):
    intercept: Literal["free", "zero"] = "free"
    weights_column: ShortText | None = None
    weights_kind: Literal["relative", "known_sigma"] = "relative"

    @model_validator(mode="after")
    def sigma_requires_column(self) -> Self:
        if self.weights_kind == "known_sigma" and self.weights_column is None:
            raise ValueError(
                "known_sigma requires a weights_column containing positive standard deviations"
            )
        return self


class FirstOrderKineticsParameters(ContractModel):
    initial_concentration: NonnegativeNumber
    rate_constant: PositiveNumber
    time_end: PositiveNumber
    points: Annotated[int, Field(ge=2, le=10_000)] = 101
    concentration_unit: Unit
    time_unit: Unit
    title: Label = ""


class ReviseFigureParameters(ContractModel):
    source_figure: Annotated[str, StringConstraints(min_length=1, max_length=4096)]
    title: Label | None = None
    x_label: Label | None = None
    y_label: Label | None = None
    x_limits: Annotated[list[FiniteNumber], Field(min_length=2, max_length=2)] | None = None
    y_limits: Annotated[list[FiniteNumber], Field(min_length=2, max_length=2)] | None = None

    @model_validator(mode="after")
    def increasing_limits(self) -> Self:
        for name in ("x_limits", "y_limits"):
            limits = getattr(self, name)
            if limits is not None and limits[0] >= limits[1]:
                raise ValueError(f"{name} must be a strictly increasing finite pair")
        return self


PARAMETER_MODELS: dict[str, type[ContractModel]] = {
    "data_profile": NoParameters,
    "plot_xy": PlotParameters,
    "linear_calibration": LinearCalibrationParameters,
    "first_order_kinetics": FirstOrderKineticsParameters,
    "revise_figure": ReviseFigureParameters,
}


class ColumnProfile(ContractModel):
    name: ShortText
    numeric: bool
    finite_count: Count
    missing_count: Count
    nonfinite_count: Count
    minimum: FiniteNumber | None
    maximum: FiniteNumber | None

    @model_validator(mode="after")
    def coherent_bounds(self) -> Self:
        if (self.minimum is None) != (self.maximum is None):
            raise ValueError("minimum and maximum must both be present or both null")
        if self.numeric and self.finite_count > 0:
            if self.minimum is None or self.maximum is None or self.minimum > self.maximum:
                raise ValueError("finite numeric values require ordered finite minimum and maximum")
        elif self.minimum is not None or self.maximum is not None:
            raise ValueError("columns without finite numeric values have null minimum and maximum")
        if not self.numeric and (self.finite_count != 0 or self.nonfinite_count != 0):
            raise ValueError("text columns do not claim finite or infinite numeric counts")
        return self


class DataProfileResult(ContractModel):
    rows: Count
    columns: Annotated[list[ColumnProfile], Field(max_length=1000)]

    @model_validator(mode="after")
    def coherent_counts(self) -> Self:
        names = [column.name for column in self.columns]
        if len(names) != len(set(names)):
            raise ValueError("column names must be unique")
        for column in self.columns:
            if column.numeric:
                if column.finite_count + column.missing_count + column.nonfinite_count != self.rows:
                    raise ValueError(
                        "numeric finite, missing (NaN), and nonfinite (Inf) counts must sum to rows"
                    )
            elif column.missing_count > self.rows:
                raise ValueError("missing text count cannot exceed rows")
        return self


class PlotXYResult(ContractModel):
    rows: Annotated[int, Field(ge=1, le=1_000_000_000)]
    x_column: ShortText
    y_column: ShortText
    x_unit: Unit
    y_unit: Unit


class LinearCalibrationResult(ContractModel):
    rows: Annotated[int, Field(ge=1, le=1_000_000_000)]
    intercept_mode: Literal["free", "zero"]
    weights_kind: Literal["relative", "known_sigma"]
    weighted: bool
    degrees_of_freedom: Count
    slope: FiniteNumber
    intercept: FiniteNumber
    slope_standard_error: NonnegativeNumber | None
    intercept_standard_error: NonnegativeNumber | None
    residual_sum_squares: NonnegativeNumber
    weighted_residual_sum_squares: NonnegativeNumber
    r_squared: FiniteNumber | None
    r_squared_reason: Reason | None = None
    uncertainty_state: Literal["available", "not_calculated"]
    uncertainty_reason: Reason | None
    x_unit: Unit
    y_unit: Unit

    @model_validator(mode="after")
    def coherent_fit(self) -> Self:
        parameter_count = 2 if self.intercept_mode == "free" else 1
        if self.rows < parameter_count or self.degrees_of_freedom != self.rows - parameter_count:
            raise ValueError("degrees_of_freedom must equal rows minus fitted parameter count")
        if self.intercept_mode == "zero" and self.intercept != 0:
            raise ValueError("a zero-intercept fit must report intercept zero")
        if self.weights_kind == "known_sigma" and not self.weighted:
            raise ValueError("known_sigma requires weighted fitting")
        if self.uncertainty_state == "available":
            if self.slope_standard_error is None or self.intercept_standard_error is None:
                raise ValueError("available uncertainty requires both standard error values")
            if self.uncertainty_reason is not None:
                raise ValueError("available uncertainty must have null unavailability reason")
            if self.weights_kind == "relative" and self.degrees_of_freedom == 0:
                raise ValueError("relative-weight uncertainty requires residual degrees of freedom")
            if self.intercept_mode == "zero" and self.intercept_standard_error != 0:
                raise ValueError(
                    "a fixed zero intercept has zero standard error when uncertainty is available"
                )
        elif (
            self.slope_standard_error is not None
            or self.intercept_standard_error is not None
            or self.uncertainty_reason is None
        ):
            raise ValueError(
                "not-calculated uncertainty requires null errors and an explicit reason"
            )
        if (self.r_squared is None) != (self.r_squared_reason is not None):
            raise ValueError(
                "null r_squared requires an explicit reason; a value requires null reason"
            )
        if self.r_squared is not None and self.r_squared > 1 + 1e-12:
            raise ValueError("r_squared cannot exceed one")
        return self


class FirstOrderKineticsResult(ContractModel):
    points: Annotated[int, Field(ge=2, le=10_000)]
    initial_concentration: NonnegativeNumber
    rate_constant: PositiveNumber
    time_end: PositiveNumber
    final_concentration: NonnegativeNumber
    max_absolute_error: NonnegativeNumber
    relative_tolerance: PositiveNumber
    absolute_tolerance: PositiveNumber
    concentration_unit: Unit
    time_unit: Unit

    @model_validator(mode="after")
    def nonincreasing_concentration(self) -> Self:
        if self.final_concentration > self.initial_concentration + self.absolute_tolerance:
            raise ValueError(
                "first-order decay cannot increase concentration beyond the solver tolerance"
            )
        return self


class ReviseFigureResult(ContractModel):
    title: Label | None
    x_label: Label | None
    y_label: Label | None
    curves_preserved: Literal[True]

    @field_validator("curves_preserved", mode="before")
    @classmethod
    def literal_is_boolean(cls, value: object) -> object:
        # Literal[True] alone also accepts integer 1 in Pydantic, even in strict mode.
        if type(value) is not bool:
            raise ValueError("curves_preserved must be a boolean")
        return value


RESULT_MODELS: dict[str, type[ContractModel]] = {
    "data_profile": DataProfileResult,
    "plot_xy": PlotXYResult,
    "linear_calibration": LinearCalibrationResult,
    "first_order_kinetics": FirstOrderKineticsResult,
    "revise_figure": ReviseFigureResult,
}
OperationResult = (
    DataProfileResult
    | PlotXYResult
    | LinearCalibrationResult
    | FirstOrderKineticsResult
    | ReviseFigureResult
)


class Metric(ContractModel):
    name: Identifier
    value: FiniteNumber | None
    unit: MetricUnit | None
    state: Literal["available", "not_calculated", "unavailable"]
    method: Reason
    reason: Reason | None = None

    @model_validator(mode="after")
    def coherent_availability(self) -> Self:
        if self.state == "available":
            if self.value is None:
                raise ValueError("available metrics require a finite value")
            if self.reason is not None:
                raise ValueError("available metric must have null unavailability reason")
        elif self.value is not None or self.reason is None:
            raise ValueError(
                "unavailable/not-calculated metrics require null value and explicit reason"
            )
        return self


class Verification(ContractModel):
    native_reopen: bool
    numerical: bool
    script_rerun: bool


class NativeArtifact(ContractModel):
    name: Filename
    role: ArtifactRole
    media_type: MediaType

    @model_validator(mode="after")
    def safe_filename(self) -> Self:
        if self.name in (".", "..") or ":" in self.name or self.name.endswith((".", " ")):
            raise ValueError("artifact names must be ordinary relative filenames")
        return self


class NativeError(ContractModel):
    code: Literal["INPUT_INVALID", "NATIVE_EXECUTION_FAILED", "NATIVE_VERIFY_FAILED", "CANCELLED"]
    message: Summary


class NativeReceipt(ContractModel):
    contract_version: Literal["1.0"]
    job_id: JobId
    operation: Operation
    state: Literal["completed", "cancelled", "failed"]
    observed_at: Timestamp
    matlab_version: ShortText
    matlab_release: ShortText
    summary: Summary
    metrics: Annotated[list[Metric], Field(max_length=100)]
    artifacts: Annotated[list[NativeArtifact], Field(max_length=100)]
    verification: Verification
    details: OperationResult | None
    error: NativeError | None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> Self:
        _check_timestamp(self.observed_at)
        if self.state == "completed":
            if self.error is not None or self.details is None:
                raise ValueError("completed receipts require details and no error")
            if not isinstance(self.details, RESULT_MODELS[self.operation]):
                raise ValueError("receipt details do not match the declared operation")
        elif self.details is not None or self.error is None:
            raise ValueError("failed/cancelled receipts require null details and an error")
        if self.state == "cancelled" and (self.error is None or self.error.code != "CANCELLED"):
            raise ValueError("cancelled receipts require the CANCELLED error code")
        if self.state == "failed" and self.error is not None and self.error.code == "CANCELLED":
            raise ValueError("CANCELLED cannot describe a failed receipt")
        names = [artifact.name for artifact in self.artifacts]
        if len(names) != len(set(names)):
            raise ValueError("artifact names must be unique")
        metric_names = [metric.name for metric in self.metrics]
        if len(metric_names) != len(set(metric_names)):
            raise ValueError("metric names must be unique")
        return self


class ErrorInfo(ContractModel):
    code: Annotated[
        str, StringConstraints(min_length=1, max_length=80, pattern=r"^[A-Z][A-Z0-9_]*$")
    ]
    message: Summary
    retryable: bool = False
    recovery: Reason | None = None


class Capability(ContractModel):
    name: Identifier
    state: Availability
    reason: Reason | None = None

    @model_validator(mode="after")
    def unavailable_has_reason(self) -> Self:
        if self.state != "available" and self.reason is None:
            raise ValueError("non-available capabilities require an explicit reason")
        return self


class BackendStatus(ContractModel):
    name: Literal["mathworks_mcp"] = "mathworks_mcp"
    state: Availability
    matlab_version: ShortText | None = None
    matlab_release: ShortText | None = None
    reason: Reason | None = None
    owned_session: bool = False

    @model_validator(mode="after")
    def unavailable_has_reason(self) -> Self:
        if self.state != "available" and self.reason is None:
            raise ValueError("non-available backend states require an explicit reason")
        return self


class Artifact(NativeArtifact):
    artifact_id: Identifier
    job_id: JobId
    size_bytes: Annotated[int, Field(ge=0, le=10_000_000_000)]
    sha256: Sha256
    uri: Uri
    verified: bool


class JobSummary(ContractModel):
    job_id: JobId
    operation: Operation
    state: JobState
    phase: JobPhase | None = None
    event_seq: EventSequence = 0
    summary: Summary
    metrics: Annotated[list[Metric], Field(max_length=100)] = Field(default_factory=list)
    verification: Verification | None = None
    artifact_count: Annotated[int, Field(ge=0, le=100)] = 0
    error: ErrorInfo | None = None

    @model_validator(mode="after")
    def completed_has_no_error(self) -> Self:
        if self.state == "completed" and self.error is not None:
            raise ValueError("a completed job cannot contain an error")
        if self.state in ("failed", "interrupted", "unknown") and self.error is None:
            raise ValueError("failed/interrupted/unknown jobs require an explanatory error")
        if self.phase is not None:
            expected = "executing" if self.state == "running" else self.state
            validating = self.phase == "validating" and self.state in {
                "running",
                "cancel_requested",
                "interrupted",
                "unknown",
            }
            if self.phase != expected and not validating:
                raise ValueError("job phase must match the observed lifecycle state")
        return self


class ResultReference(ContractModel):
    operation: Operation
    contract_version: Literal["1.0"] = "1.0"
    schema_uri: Uri
    result_uri: Uri


class OperationHelp(ContractModel):
    operation: Operation
    summary: Summary
    requires_input: bool
    parameter_schema_uri: Uri
    result_schema_uri: Uri


class InputInspection(ContractModel):
    input_id: Identifier
    name: Filename
    media_type: MediaType
    size_bytes: Annotated[int, Field(ge=0, le=10_000_000_000)]
    sha256: Sha256
    trust: Literal["tabular_input", "owned_artifact", "untrusted_native"]
    profile: DataProfileResult | None = None


class DeliveryReceipt(ContractModel):
    artifact_id: Identifier
    state: Literal["not_delivered", "available", "delivered", "verified", "failed"]
    method: Literal["mcp_resource", "local_copy", "host_attachment"]
    destination: Annotated[str, StringConstraints(min_length=1, max_length=2048)] | None = None
    size_bytes: Annotated[int, Field(ge=0, le=10_000_000_000)] | None = None
    sha256: Sha256 | None = None
    reason: Reason | None = None

    @model_validator(mode="after")
    def verified_delivery_has_evidence(self) -> Self:
        if self.state == "delivered" and self.destination is None:
            raise ValueError("delivered files require a destination reference")
        if self.state == "verified" and (
            self.destination is None or self.size_bytes is None or self.sha256 is None
        ):
            raise ValueError("verified delivery requires destination, size and SHA-256 evidence")
        if self.state in ("failed", "not_delivered") and self.reason is None:
            raise ValueError("failed/not-delivered states require a reason")
        return self


class ToolOutput(ContractModel):
    contract_version: Literal["1.0"] = "1.0"
    request_id: JobId
    observed_at: Timestamp
    ok: bool
    job_id: JobId | None = None
    error: ErrorInfo | None = None

    @model_validator(mode="after")
    def coherent_result(self) -> Self:
        _check_timestamp(self.observed_at)
        if self.ok != (self.error is None):
            raise ValueError("ok must be true exactly when the tool invocation has no error")
        job = getattr(self, "job", None)
        if job is not None and self.job_id != job.job_id:
            raise ValueError("outer job_id must preserve the returned job identity")
        return self


class RuntimeStatistics(ContractModel):
    max_active_jobs: Literal[10] = MAX_ACTIVE_JOBS
    active_jobs: Count | None
    retained_jobs: Count
    storage_bytes: Annotated[int, Field(ge=0, le=2**53 - 1)]
    storage_complete: bool
    retention: Literal["explicit_removal_only"] = "explicit_removal_only"
    automatic_cleanup: Literal[False] = False
    observed_at: Timestamp

    @field_validator("max_active_jobs", mode="before")
    @classmethod
    def active_limit_is_an_integer(cls, value):
        if type(value) is not int:
            raise ValueError("max_active_jobs must be an integer")
        return value

    @field_validator("automatic_cleanup", mode="before")
    @classmethod
    def cleanup_is_a_boolean(cls, value):
        if value is not False:
            raise ValueError("automatic_cleanup must be the boolean false")
        return value

    @model_validator(mode="after")
    def accounting_is_coherent(self) -> Self:
        _check_timestamp(self.observed_at)
        if self.storage_complete:
            if self.active_jobs is None or self.active_jobs > self.retained_jobs:
                raise ValueError("complete accounting requires a coherent active job count")
        elif self.active_jobs is not None:
            raise ValueError("incomplete accounting cannot claim a complete active job count")
        return self


class StatusOutput(ToolOutput):
    operation: Literal["matlab_status"] = "matlab_status"
    backend: BackendStatus | None = None
    capabilities: Annotated[list[Capability], Field(max_length=50)] = Field(default_factory=list)
    runtime: RuntimeStatistics | None = None

    @model_validator(mode="after")
    def success_has_backend(self) -> Self:
        if self.ok and self.backend is None:
            raise ValueError("successful status requires a backend observation")
        return self


class HelpOutput(ToolOutput):
    operation: Literal["matlab_help"] = "matlab_help"
    operations: Annotated[list[OperationHelp], Field(max_length=5)] = Field(default_factory=list)
    next_cursor: Identifier | None = None


class InspectOutput(ToolOutput):
    operation: Literal["matlab_inspect"] = "matlab_inspect"
    input: InputInspection | None = None

    @model_validator(mode="after")
    def success_has_input(self) -> Self:
        if self.ok and self.input is None:
            raise ValueError("successful inspection requires input metadata")
        return self


class RunOutput(ToolOutput):
    operation: Literal["matlab_run"] = "matlab_run"
    job: JobSummary | None = None

    @model_validator(mode="after")
    def success_has_job(self) -> Self:
        if self.ok and self.job is None:
            raise ValueError("accepted runs require a stable job summary")
        return self


class JobOutput(ToolOutput):
    operation: Literal["matlab_job"] = "matlab_job"
    job: JobSummary | None = None
    result: ResultReference | None = None

    @model_validator(mode="after")
    def result_matches_job(self) -> Self:
        if self.ok and self.job is None:
            raise ValueError("successful job queries require a job summary")
        if self.result is not None and (
            self.job is None
            or self.job.state != "completed"
            or self.result.operation != self.job.operation
        ):
            raise ValueError("result references require the matching completed job")
        return self


class ArtifactsOutput(ToolOutput):
    operation: Literal["matlab_artifacts"] = "matlab_artifacts"
    artifacts: Annotated[list[Artifact], Field(max_length=100)] = Field(default_factory=list)
    delivery: DeliveryReceipt | None = None
    next_cursor: Identifier | None = None

    @model_validator(mode="after")
    def artifacts_match_job(self) -> Self:
        if self.job_id is not None and any(item.job_id != self.job_id for item in self.artifacts):
            raise ValueError("listed artifacts must belong to the identified job")
        if self.delivery is not None and self.delivery.artifact_id not in {
            item.artifact_id for item in self.artifacts
        }:
            raise ValueError("delivery receipt must identify an artifact returned in this response")
        return self


class SingleArtifactOutput(ArtifactsOutput):
    @model_validator(mode="after")
    def identifies_one_original(self) -> Self:
        if self.ok and len(self.artifacts) != 1:
            raise ValueError("successful artifact reads require exactly one original artifact")
        return self


class ArtifactReadOutput(SingleArtifactOutput):
    @model_validator(mode="after")
    def oversized_read_requires_local_delivery(self) -> Self:
        if self.ok and self.artifacts[0].size_bytes > MAX_INLINE_BYTES:
            artifact = self.artifacts[0]
            delivery = self.delivery
            if (
                delivery is None
                or delivery.state != "not_delivered"
                or delivery.method != "local_copy"
                or delivery.destination is not None
                or delivery.size_bytes != artifact.size_bytes
                or delivery.sha256 != artifact.sha256
            ):
                raise ValueError(
                    "over-limit artifact reads require pending local delivery with matching size and SHA-256"
                )
        return self


class ArtifactDeliverOutput(SingleArtifactOutput):
    @model_validator(mode="after")
    def has_delivery_receipt(self) -> Self:
        if self.ok and self.delivery is None:
            raise ValueError(
                "successful delivery operations require an independent delivery receipt"
            )
        if (
            self.ok
            and self.delivery is not None
            and self.delivery.state not in ("delivered", "verified")
        ):
            raise ValueError(
                "successful delivery operations must report delivered or verified bytes"
            )
        return self


class ResultReadOutput(ArtifactsOutput):
    @model_validator(mode="after")
    def identifies_result_job(self) -> Self:
        if self.ok and self.job_id is None:
            raise ValueError("successful operation-result reads require a job identity")
        return self


TOOL_OUTPUT_MODELS: dict[str, type[ToolOutput]] = {
    "matlab_status": StatusOutput,
    "matlab_help": HelpOutput,
    "matlab_inspect": InspectOutput,
    "matlab_run": RunOutput,
    "matlab_job": JobOutput,
    "matlab_artifacts": ArtifactsOutput,
}

# Action schemas stay discoverable without expanding the six-tool catalog. The
# native scientific results have their own registry rather than appearing here.
DISPATCH_OUTPUT_MODELS: dict[str, type[ToolOutput]] = {
    "matlab_job.status": JobOutput,
    "matlab_job.cancel": JobOutput,
    "matlab_job.reconcile": JobOutput,
    "matlab_job.wait": JobOutput,
    "matlab_artifacts.list": ArtifactsOutput,
    "matlab_artifacts.read": ArtifactReadOutput,
    "matlab_artifacts.deliver": ArtifactDeliverOutput,
    "matlab_artifacts.read_result": ResultReadOutput,
    "matlab_artifacts.read_schema": ArtifactsOutput,
}


def validate_parameters(operation: str, parameters: dict) -> dict:
    """Validate without string/boolean numeric coercion and materialize defaults."""
    if operation not in PARAMETER_MODELS:
        raise ValueError(f"unsupported operation: {operation}")
    return PARAMETER_MODELS[operation].model_validate(parameters).model_dump(mode="json")


def validate_operation_result(operation: str, result: dict) -> ContractModel:
    if operation not in RESULT_MODELS:
        raise ValueError(f"unsupported operation: {operation}")
    return RESULT_MODELS[operation].model_validate(result)


def validate_native_receipt(receipt: dict) -> NativeReceipt:
    return NativeReceipt.model_validate(receipt)


def tool_output_model(tool_name: str) -> type[ToolOutput]:
    if tool_name not in TOOL_OUTPUT_MODELS:
        raise ValueError(f"unsupported tool: {tool_name}")
    return TOOL_OUTPUT_MODELS[tool_name]


def validate_dispatch_output(tool_name: str, action: str, payload: dict) -> ToolOutput:
    route = f"{tool_name}.{action}"
    if route not in DISPATCH_OUTPUT_MODELS:
        raise ValueError(f"unsupported dispatch route: {route}")
    return DISPATCH_OUTPUT_MODELS[route].model_validate(payload)


def dispatch_schemas() -> dict[str, dict]:
    return {
        route: {"contract_version": CONTRACT_VERSION, "result": model.model_json_schema()}
        for route, model in DISPATCH_OUTPUT_MODELS.items()
    }


def operation_schemas() -> dict[str, dict]:
    """Return the compact registry's separately discoverable operation schemas."""
    return {
        operation: {
            "contract_version": CONTRACT_VERSION,
            "parameters": PARAMETER_MODELS[operation].model_json_schema(),
            "result": RESULT_MODELS[operation].model_json_schema(),
        }
        for operation in PARAMETER_MODELS
    }
