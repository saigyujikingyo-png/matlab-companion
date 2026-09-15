"""Contract safety tests: independent fixtures, malformed native output and public branches."""

from __future__ import annotations

import copy
import json

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from matlab_companion.contracts import (
    DISPATCH_OUTPUT_MODELS,
    RESULT_MODELS,
    TOOL_OUTPUT_MODELS,
    Artifact,
    ColumnProfile,
    DeliveryReceipt,
    Metric,
    NativeReceipt,
    dispatch_schemas,
    operation_schemas,
    tool_output_model,
    validate_dispatch_output,
    validate_native_receipt,
    validate_operation_result,
    validate_parameters,
)

JOB_ID = "4eac118d-5336-4722-bd43-183a797d8303"
REQUEST_ID = "1e8398e0-9de3-4a6a-8494-cd7876a2e9b2"
OTHER_JOB = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
OBSERVED = "2026-09-15T15:00:00Z"
SHA = "a" * 64


@pytest.fixture
def details() -> dict[str, dict]:
    # The calibration fixture is y=2*x+1 on x=[0,1,2], independently known exactly.
    return {
        "data_profile": {
            "rows": 4,
            "columns": [
                {
                    "name": "x",
                    "numeric": True,
                    "finite_count": 2,
                    "missing_count": 1,
                    "nonfinite_count": 1,
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
                {
                    "name": "label",
                    "numeric": False,
                    "finite_count": 0,
                    "missing_count": 1,
                    "nonfinite_count": 0,
                    "minimum": None,
                    "maximum": None,
                },
            ],
        },
        "plot_xy": {"rows": 3, "x_column": "x", "y_column": "y", "x_unit": "s", "y_unit": "mol/L"},
        "linear_calibration": {
            "rows": 3,
            "intercept_mode": "free",
            "weights_kind": "relative",
            "weighted": False,
            "degrees_of_freedom": 1,
            "slope": 2.0,
            "intercept": 1.0,
            "slope_standard_error": 0.0,
            "intercept_standard_error": 0.0,
            "residual_sum_squares": 0.0,
            "weighted_residual_sum_squares": 0.0,
            "r_squared": 1.0,
            "r_squared_reason": None,
            "uncertainty_state": "available",
            "uncertainty_reason": None,
            "x_unit": "mg/L",
            "y_unit": "1",
        },
        "first_order_kinetics": {
            "points": 101,
            "initial_concentration": 1.0,
            "rate_constant": 0.1,
            "time_end": 10.0,
            "final_concentration": 0.36787944117144233,
            "max_absolute_error": 1e-9,
            "relative_tolerance": 1e-8,
            "absolute_tolerance": 1e-10,
            "concentration_unit": "mol/L",
            "time_unit": "s",
        },
        "revise_figure": {
            "title": "Revised title",
            "x_label": None,
            "y_label": None,
            "curves_preserved": True,
        },
    }


def native_receipt(operation: str, details: dict | None, state: str = "completed") -> dict:
    return {
        "contract_version": "1.0",
        "job_id": JOB_ID,
        "operation": operation,
        "state": state,
        "observed_at": OBSERVED,
        "matlab_version": "25.2.0",
        "matlab_release": "R2025b",
        "summary": "Synthetic fixture result.",
        "metrics": [],
        "artifacts": [
            {
                "name": "analysis.mat",
                "role": "native_data",
                "media_type": "application/x-matlab-data",
            }
        ],
        "verification": {"native_reopen": True, "numerical": True, "script_rerun": False},
        "details": details,
        "error": None
        if state == "completed"
        else {
            "code": "CANCELLED" if state == "cancelled" else "NATIVE_EXECUTION_FAILED",
            "message": "Cancelled at a safe boundary."
            if state == "cancelled"
            else "Native operation failed.",
        },
    }


def public_artifact() -> dict:
    return {
        "name": "figure.fig",
        "role": "native_figure",
        "media_type": "application/x-matlab-figure",
        "artifact_id": "fixture-figure",
        "job_id": JOB_ID,
        "size_bytes": 1024,
        "sha256": SHA,
        "uri": f"matlab-companion://artifacts/{JOB_ID}/fixture-figure",
        "verified": True,
    }


def public_examples() -> dict[str, dict]:
    common = {"request_id": REQUEST_ID, "observed_at": OBSERVED, "ok": True}
    queued = {
        "job_id": JOB_ID,
        "operation": "plot_xy",
        "state": "queued",
        "summary": "Awaiting the owned MATLAB executor.",
    }
    completed = {
        **queued,
        "state": "completed",
        "summary": "Created an editable figure.",
        "artifact_count": 1,
        "verification": {"native_reopen": True, "numerical": True, "script_rerun": True},
    }
    return {
        "matlab_status": {
            **common,
            "backend": {
                "state": "unverified",
                "reason": "Passive discovery does not launch MATLAB.",
            },
            "capabilities": [
                {"name": "plot_xy", "state": "unverified", "reason": "Native acceptance pending."}
            ],
        },
        "matlab_help": {
            **common,
            "operations": [
                {
                    "operation": "plot_xy",
                    "summary": "Plot two named CSV columns.",
                    "requires_input": True,
                    "parameter_schema_uri": "matlab-companion://schemas/plot_xy/parameters",
                    "result_schema_uri": "matlab-companion://schemas/plot_xy/result",
                }
            ],
        },
        "matlab_inspect": {
            **common,
            "input": {
                "input_id": "input-1",
                "name": "fixture.csv",
                "media_type": "text/csv",
                "size_bytes": 19,
                "sha256": SHA,
                "trust": "tabular_input",
            },
        },
        "matlab_run": {**common, "job_id": JOB_ID, "job": queued},
        "matlab_job": {
            **common,
            "job_id": JOB_ID,
            "job": completed,
            "result": {
                "operation": "plot_xy",
                "schema_uri": "matlab-companion://schemas/plot_xy/result",
                "result_uri": f"matlab-companion://results/{JOB_ID}",
            },
        },
        "matlab_artifacts": {
            **common,
            "job_id": JOB_ID,
            "artifacts": [public_artifact()],
            "delivery": {
                "artifact_id": "fixture-figure",
                "state": "available",
                "method": "mcp_resource",
            },
        },
    }


@pytest.mark.parametrize("operation", list(RESULT_MODELS))
def test_each_operation_native_receipt_and_schema(operation, details):
    raw = native_receipt(operation, details[operation])
    receipt = validate_native_receipt(raw)
    assert receipt.job_id == JOB_ID
    assert isinstance(receipt.details, RESULT_MODELS[operation])
    Draft202012Validator(NativeReceipt.model_json_schema()).validate(
        receipt.model_dump(mode="json")
    )
    result = validate_operation_result(operation, details[operation])
    Draft202012Validator(operation_schemas()[operation]["result"]).validate(
        result.model_dump(mode="json")
    )


@pytest.mark.parametrize("tool_name", list(TOOL_OUTPUT_MODELS))
def test_each_public_tool_success_error_and_json_fallback(tool_name):
    model = tool_output_model(tool_name)
    schema = model.model_json_schema()
    Draft202012Validator.check_schema(schema)
    accepted = model.model_validate(public_examples()[tool_name])
    # The canonical fallback has exactly the same values, including nulls, as structuredContent.
    structured = accepted.model_dump(mode="json")
    assert json.loads(accepted.model_dump_json()) == structured
    Draft202012Validator(schema).validate(structured)
    error = model.model_validate(
        {
            "request_id": REQUEST_ID,
            "observed_at": OBSERVED,
            "ok": False,
            "job_id": JOB_ID,
            "error": {
                "code": "OUTPUT_VALIDATION_FAILED",
                "message": "Malformed native output; reconcile the known job before retrying.",
            },
        }
    )
    Draft202012Validator(schema).validate(error.model_dump(mode="json"))
    assert error.job_id == JOB_ID
    assert error.error.retryable is False


def test_output_schemas_are_bounded_objects_without_operation_union():
    for model in TOOL_OUTPUT_MODELS.values():
        schema = model.model_json_schema()
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert len(json.dumps(schema).encode()) < 12_000
        for definition in schema.get("$defs", {}).values():
            if definition.get("type") == "object":
                assert definition["additionalProperties"] is False
        assert "LinearCalibrationResult" not in schema.get("$defs", {})
    assert set(operation_schemas()) == set(RESULT_MODELS)


@pytest.mark.parametrize(
    "operation,parameters",
    [
        ("data_profile", {}),
        ("plot_xy", {"x_column": "time", "y_column": "signal", "x_unit": "s", "y_unit": "1"}),
        (
            "linear_calibration",
            {
                "x_column": "concentration",
                "y_column": "signal",
                "x_unit": "mg/L",
                "y_unit": "1",
                "weights_column": "sigma",
                "weights_kind": "known_sigma",
            },
        ),
        (
            "first_order_kinetics",
            {
                "initial_concentration": 1.0,
                "rate_constant": 0.1,
                "time_end": 20.0,
                "concentration_unit": "mol/L",
                "time_unit": "s",
            },
        ),
        ("revise_figure", {"source_figure": "C:/owned/job/figure.fig", "x_limits": [0.0, 1.0]}),
    ],
)
def test_each_parameter_model_and_discoverable_schema(operation, parameters):
    validated = validate_parameters(operation, parameters)
    Draft202012Validator(operation_schemas()[operation]["parameters"]).validate(validated)
    if operation == "first_order_kinetics":
        assert validated["points"] == 101
    if operation == "linear_calibration":
        assert validated["intercept"] == "free"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), "0.1", True])
def test_bad_numeric_input_never_reaches_matlab(value):
    with pytest.raises(ValidationError):
        validate_parameters(
            "first_order_kinetics",
            {
                "initial_concentration": 1.0,
                "rate_constant": value,
                "time_end": 2.0,
                "concentration_unit": "mol/L",
                "time_unit": "s",
            },
        )


@pytest.mark.parametrize(
    "operation,parameters",
    [
        ("data_profile", {"delete_missing": True}),
        ("plot_xy", {"x_column": "x", "y_column": "y", "x_unit": "", "y_unit": "1"}),
        (
            "linear_calibration",
            {
                "x_column": "x",
                "y_column": "y",
                "x_unit": "s",
                "y_unit": "1",
                "weights_kind": "known_sigma",
            },
        ),
        (
            "first_order_kinetics",
            {
                "initial_concentration": 1.0,
                "rate_constant": 0.1,
                "time_end": 2.0,
                "points": 2.5,
                "concentration_unit": "mol/L",
                "time_unit": "s",
            },
        ),
        ("revise_figure", {"source_figure": "owned.fig", "x_limits": [1.0, 1.0]}),
        ("revise_figure", {"source_figure": "owned.fig", "y_limits": [2.0, 1.0]}),
        ("revise_figure", {"source_figure": "owned.fig", "x_limits": [1.0]}),
    ],
)
def test_semantically_invalid_parameter_requests_are_rejected(operation, parameters):
    with pytest.raises(ValidationError):
        validate_parameters(operation, parameters)


@pytest.mark.parametrize("state", ["failed", "cancelled"])
def test_native_failure_preserves_job_and_partial_artifact_metadata(state):
    receipt = validate_native_receipt(native_receipt("plot_xy", None, state))
    assert receipt.job_id == JOB_ID
    assert receipt.artifacts[0].name == "analysis.mat"
    assert receipt.details is None
    assert receipt.error is not None


@pytest.mark.parametrize(
    "mutation",
    [
        {"job_id": "lost-id"},
        {"contract_version": "2.0"},
        {"state": "running"},
        {"observed_at": "2026-02-30T15:00:00Z"},
        {"observed_at": "2026-09-15T15:00:00+01:00"},
        {"details": {}},
        {"details": None},
        {"operation": "data_profile"},
        {"error": {"code": "NATIVE_EXECUTION_FAILED", "message": "contradictory success"}},
        {"private_stack_trace": "must not escape"},
    ],
)
def test_malformed_native_receipt_is_not_valid_success(mutation, details):
    receipt = native_receipt("plot_xy", details["plot_xy"])
    receipt.update(mutation)
    with pytest.raises(ValidationError):
        validate_native_receipt(receipt)


@pytest.mark.parametrize(
    "state,error,details_value",
    [
        ("failed", None, None),
        ("cancelled", {"code": "NATIVE_EXECUTION_FAILED", "message": "wrong lifecycle"}, None),
        ("failed", {"code": "CANCELLED", "message": "wrong lifecycle"}, None),
        ("failed", {"code": "NATIVE_EXECUTION_FAILED", "message": "wrong details"}, {}),
    ],
)
def test_invalid_failure_branches_rejected(state, error, details_value):
    receipt = native_receipt("plot_xy", details_value, state)
    receipt["error"] = error
    with pytest.raises(ValidationError):
        validate_native_receipt(receipt)


def test_metrics_distinguish_zero_unknown_units_and_not_calculated():
    zero = Metric(
        name="offset", value=0.0, unit=None, state="available", method="Unweighted least squares"
    )
    assert zero.value == 0 and zero.unit is None
    unavailable = Metric(
        name="slope_standard_error",
        value=None,
        unit="L/mg",
        state="not_calculated",
        method="Residual variance estimate",
        reason="No residual degrees of freedom.",
    )
    assert unavailable.value is None


@pytest.mark.parametrize(
    "override",
    [
        {"value": None},
        {"value": float("nan")},
        {"value": True},
        {"state": "unavailable"},
        {"reason": "unavailable despite value"},
        {"state": "not_calculated", "value": None},
        {"unit": ""},
    ],
)
def test_invalid_metric_semantics_rejected(override):
    metric = {
        "name": "slope",
        "value": 2.0,
        "unit": "1",
        "state": "available",
        "method": "Least squares",
    }
    metric.update(override)
    with pytest.raises(ValidationError):
        Metric.model_validate(metric)


def test_empty_numeric_column_reports_no_invented_extrema():
    column = ColumnProfile(
        name="empty",
        numeric=True,
        finite_count=0,
        missing_count=2,
        nonfinite_count=0,
        minimum=None,
        maximum=None,
    )
    assert column.minimum is None
    raw = column.model_dump()
    raw.update(minimum=0.0, maximum=0.0)
    with pytest.raises(ValidationError):
        ColumnProfile.model_validate(raw)


def test_profile_counts_and_names_reject_misleading_summary(details):
    raw = details["data_profile"]
    raw["columns"][0]["missing_count"] = 2
    with pytest.raises(ValidationError):
        validate_operation_result("data_profile", raw)
    raw["columns"][0]["missing_count"] = 1
    raw["columns"].append(copy.deepcopy(raw["columns"][0]))
    with pytest.raises(ValidationError):
        validate_operation_result("data_profile", raw)


@pytest.mark.parametrize(
    "override",
    [
        {"degrees_of_freedom": 3},
        {"intercept_mode": "zero"},
        {"weights_kind": "known_sigma"},
        {"r_squared": None},
        {"r_squared": 1.2},
        {"slope": float("inf")},
        {"slope_standard_error": None},
        {"uncertainty_state": "not_calculated"},
        {"uncertainty_reason": "cannot be unavailable and calculated"},
    ],
)
def test_fit_result_rejects_wrong_dof_units_missingness_and_nonfinite(override, details):
    raw = details["linear_calibration"]
    raw.update(override)
    with pytest.raises(ValidationError):
        validate_operation_result("linear_calibration", raw)


def test_undefined_fit_quality_and_uncalculated_uncertainty_are_explicit(details):
    raw = details["linear_calibration"]
    raw.update(
        rows=2,
        degrees_of_freedom=0,
        slope_standard_error=None,
        intercept_standard_error=None,
        uncertainty_state="not_calculated",
        uncertainty_reason="No residual degrees of freedom.",
        r_squared=None,
        r_squared_reason="The response is constant.",
    )
    result = validate_operation_result("linear_calibration", raw)
    assert result.r_squared is None and result.uncertainty_reason


def test_kinetics_cannot_claim_growth_in_a_decay_operation(details):
    raw = details["first_order_kinetics"]
    raw["final_concentration"] = 2.0
    with pytest.raises(ValidationError):
        validate_operation_result("first_order_kinetics", raw)


@pytest.mark.parametrize("value", [False, 1, "true"])
def test_figure_edit_requires_actual_boolean_preservation(value, details):
    raw = details["revise_figure"]
    raw["curves_preserved"] = value
    with pytest.raises(ValidationError):
        validate_operation_result("revise_figure", raw)


@pytest.mark.parametrize(
    "override",
    [
        {"name": "../source.fig"},
        {"name": "C:\\private\\source.fig"},
        {"name": ".."},
        {"name": "file:stream"},
        {"name": "file.fig "},
        {"size_bytes": -1},
        {"size_bytes": 1.5},
        {"sha256": "not-verified"},
        {"role": "any_arbitrary_role"},
        {"media_type": "unknown"},
        {"uri": "relative/path"},
        {"verified": "yes"},
    ],
)
def test_artifact_metadata_rejects_unsafe_or_unverified_shapes(override):
    raw = public_artifact()
    raw.update(override)
    with pytest.raises(ValidationError):
        Artifact.model_validate(raw)


def test_native_artifact_and_metric_identifiers_are_unique(details):
    receipt = native_receipt("plot_xy", details["plot_xy"])
    receipt["artifacts"] *= 2
    with pytest.raises(ValidationError):
        validate_native_receipt(receipt)
    receipt["artifacts"] = receipt["artifacts"][:1]
    metric = {
        "name": "rows",
        "value": 3.0,
        "unit": "1",
        "state": "available",
        "method": "Row count",
    }
    receipt["metrics"] = [metric, metric]
    with pytest.raises(ValidationError):
        validate_native_receipt(receipt)


def test_resource_availability_does_not_imply_file_delivery():
    resource = DeliveryReceipt(artifact_id="fixture", state="available", method="mcp_resource")
    assert resource.sha256 is None and resource.destination is None
    with pytest.raises(ValidationError):
        DeliveryReceipt(artifact_id="fixture", state="verified", method="mcp_resource")
    received = DeliveryReceipt(
        artifact_id="fixture",
        state="verified",
        method="local_copy",
        destination="C:/chosen/figure.fig",
        size_bytes=1024,
        sha256=SHA,
    )
    assert received.state == "verified"


def test_failed_job_query_is_successful_query_with_failed_payload():
    raw = public_examples()["matlab_job"]
    raw["result"] = None
    raw["job"].update(
        state="failed", error={"code": "NATIVE_EXECUTION_FAILED", "message": "Execution failed."}
    )
    output = tool_output_model("matlab_job").model_validate(raw)
    assert output.ok is True and output.error is None and output.job.state == "failed"


def test_job_ids_cannot_disappear_or_change_after_acceptance():
    raw = public_examples()["matlab_run"]
    for invalid_id in [None, OTHER_JOB]:
        raw["job_id"] = invalid_id
        with pytest.raises(ValidationError):
            tool_output_model("matlab_run").model_validate(raw)


def test_result_reference_cannot_anticipate_completion_or_change_operation():
    raw = public_examples()["matlab_job"]
    raw["job"]["state"] = "running"
    with pytest.raises(ValidationError):
        tool_output_model("matlab_job").model_validate(raw)
    raw["job"]["state"] = "completed"
    raw["result"]["operation"] = "linear_calibration"
    with pytest.raises(ValidationError):
        tool_output_model("matlab_job").model_validate(raw)


def test_artifact_and_delivery_cannot_cross_job_identity():
    raw = public_examples()["matlab_artifacts"]
    raw["job_id"] = OTHER_JOB
    with pytest.raises(ValidationError):
        tool_output_model("matlab_artifacts").model_validate(raw)
    raw["job_id"] = JOB_ID
    raw["delivery"]["artifact_id"] = "unlisted-artifact"
    with pytest.raises(ValidationError):
        tool_output_model("matlab_artifacts").model_validate(raw)


@pytest.mark.parametrize("tool_name", list(TOOL_OUTPUT_MODELS))
def test_ok_flag_and_error_must_agree(tool_name):
    raw = public_examples()[tool_name]
    raw["error"] = {"code": "INPUT_INVALID", "message": "Not success."}
    with pytest.raises(ValidationError):
        tool_output_model(tool_name).model_validate(raw)
    raw["error"] = None
    raw["ok"] = False
    with pytest.raises(ValidationError):
        tool_output_model(tool_name).model_validate(raw)


@pytest.mark.parametrize(
    "function,args",
    [
        (validate_parameters, ("shell", {})),
        (validate_operation_result, ("shell", {})),
        (tool_output_model, ("matlab_shell",)),
    ],
)
def test_unregistered_dispatch_is_rejected(function, args):
    with pytest.raises(ValueError, match="unsupported"):
        function(*args)


@pytest.mark.parametrize("route", list(DISPATCH_OUTPUT_MODELS))
def test_each_dispatch_route_has_validated_success_and_error(route):
    tool_name, action = route.split(".")
    raw = public_examples()[tool_name]
    if action == "deliver":
        raw["delivery"].update(
            state="verified",
            method="local_copy",
            destination="C:/chosen/figure.fig",
            size_bytes=1024,
            sha256=SHA,
        )
    output = validate_dispatch_output(tool_name, action, raw)
    schema = dispatch_schemas()[route]["result"]
    Draft202012Validator(schema).validate(output.model_dump(mode="json"))
    failure = {
        "request_id": REQUEST_ID,
        "observed_at": OBSERVED,
        "ok": False,
        "job_id": JOB_ID,
        "error": {"code": "INPUT_INVALID", "message": "Unknown artifact or action argument."},
    }
    error = validate_dispatch_output(tool_name, action, failure)
    Draft202012Validator(schema).validate(error.model_dump(mode="json"))
    assert error.job_id == JOB_ID


@pytest.mark.parametrize(
    "action,mutation",
    [
        ("read", {"artifacts": [], "delivery": None}),
        ("deliver", {"delivery": None}),
        ("read_result", {"job_id": None}),
    ],
)
def test_dispatch_cannot_report_success_without_required_identity_or_receipt(action, mutation):
    raw = public_examples()["matlab_artifacts"]
    raw.update(mutation)
    with pytest.raises(ValidationError):
        validate_dispatch_output("matlab_artifacts", action, raw)


def test_deliver_action_cannot_claim_resource_availability_as_delivery():
    raw = public_examples()["matlab_artifacts"]
    with pytest.raises(ValidationError, match="delivered or verified"):
        validate_dispatch_output("matlab_artifacts", "deliver", raw)


def test_unknown_dispatch_route_is_rejected():
    with pytest.raises(ValueError, match="unsupported dispatch route"):
        validate_dispatch_output("matlab_artifacts", "publish", {})


def test_relative_weights_do_not_manufacture_uncertainty_without_residual_dof(details):
    raw = details["linear_calibration"]
    raw.update(rows=2, degrees_of_freedom=0)
    with pytest.raises(ValidationError, match="residual degrees of freedom"):
        validate_operation_result("linear_calibration", raw)


def test_composite_metric_units_preserve_two_maximum_length_input_units():
    unit = f"({'y' * 120})/({'x' * 120})"
    metric = Metric(name="slope", value=1.0, unit=unit, state="available", method="Least squares")
    assert metric.unit == unit


@pytest.mark.parametrize(
    "state",
    [
        "queued",
        "running",
        "cancel_requested",
        "completed",
        "cancelled",
        "failed",
        "interrupted",
        "unknown",
    ],
)
def test_public_job_lifecycle_states_remain_explicit(state):
    raw = public_examples()["matlab_job"]
    raw["result"] = None
    raw["job"]["state"] = state
    if state in ("failed", "interrupted", "unknown"):
        raw["job"]["error"] = {
            "code": "EXECUTION_INTERRUPTED",
            "message": "Reconcile the original job before retrying.",
        }
    output = tool_output_model("matlab_job").model_validate(raw)
    assert output.job.state == state
    assert output.ok is True


@pytest.mark.parametrize("state", ["unavailable", "unsupported", "unverified"])
def test_unavailable_capability_and_backend_observations_require_reasons(state):
    raw = public_examples()["matlab_status"]
    raw["backend"] = {"state": state}
    with pytest.raises(ValidationError):
        tool_output_model("matlab_status").model_validate(raw)
    raw["backend"]["reason"] = "Native capability has not been established."
    raw["capabilities"] = [{"name": "native_execution", "state": state}]
    with pytest.raises(ValidationError):
        tool_output_model("matlab_status").model_validate(raw)
    raw["capabilities"][0]["reason"] = "Native acceptance is a separate gate."
    assert tool_output_model("matlab_status").model_validate(raw).backend.state == state
