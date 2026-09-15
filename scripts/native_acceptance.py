"""Explicit native acceptance on a licensed device; never run by portable CI."""

import argparse
import math
import time
from pathlib import Path

from matlab_companion.core import Core
from matlab_companion.storage import atomic_json, default_root, digest, utc_now


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="verification/native-acceptance.json")
    args = parser.parse_args()
    run_root = default_root() / "acceptance" / ("integrated-" + str(time.time_ns()))
    inputs, delivered = run_root / "fixtures", run_root / "delivered"
    inputs.mkdir(parents=True)
    source = inputs / "calibration.csv"
    source.write_text(
        "x,y,relative,sigma\n0,1,1,0.2\n1,3.1,2,0.1\n2,4.9,1,0.2\n3,7.2,0.5,0.3\n4,8.8,3,0.1\n",
        encoding="utf-8",
        newline="\n",
    )
    original_hash = digest(source)
    core = Core(run_root / "store", [inputs], [delivered])
    evidence = {
        "scope": "Synthetic native execution, numerical/native readback and local copy delivery; not host-model or installer acceptance",
        "observed_at": utc_now(),
        "cases": [],
    }
    print("Native acceptance workspace:", run_root, flush=True)
    try:
        inspected = core.call("matlab_inspect", {"path": str(source)})
        assert inspected["ok"], inspected
        input_id = inspected["input"]["input_id"]

        def run_case(name, operation, parameters, **extra):
            started = time.monotonic()
            request = {
                "operation": operation,
                "parameters": parameters,
                "idempotency_key": name,
                **extra,
            }
            if operation not in {"first_order_kinetics", "revise_figure"}:
                request["input_id"] = input_id
            accepted = core.call("matlab_run", request)
            assert accepted["ok"], accepted
            state = core.wait(accepted["job_id"], timeout=360)
            print(name, state["state"], round(time.monotonic() - started, 2), flush=True)
            assert state["state"] == "completed", state
            result = core.result(state["job_id"])
            artifacts = core.call("matlab_artifacts", {"job_id": state["job_id"]})["artifacts"]
            for artifact in artifacts:
                output = core.call(
                    "matlab_artifacts",
                    {
                        "job_id": state["job_id"],
                        "action": "deliver",
                        "artifact_id": artifact["artifact_id"],
                        "destination": str(delivered / name / artifact["name"]),
                    },
                )
                assert output["ok"] and output["delivery"]["state"] == "verified", output
            evidence["cases"].append(
                {
                    "name": name,
                    "job_id": state["job_id"],
                    "operation": operation,
                    "seconds": round(time.monotonic() - started, 3),
                    "verification": state["verification"],
                    "result": result,
                    "artifacts": [
                        {k: a[k] for k in ("name", "size_bytes", "sha256", "role")}
                        for a in artifacts
                    ],
                    "local_delivery_readback": True,
                }
            )
            return state, result, artifacts

        common = {
            "x_column": "x",
            "y_column": "y",
            "x_unit": "mmol/L",
            "y_unit": "1",
            "title": "Synthetic calibration",
        }
        relative, result, artifacts = run_case(
            "relative-calibration", "linear_calibration", common | {"weights_column": "relative"}
        )
        assert math.isclose(result["slope"], 1.9339622641509433, rel_tol=1e-11)
        assert math.isclose(result["intercept"], 1.1007547169811314, rel_tol=1e-11)
        assert math.isclose(result["slope_standard_error"], 0.03676099283911709, rel_tol=1e-10)
        _, result, _ = run_case(
            "known-sigma-calibration",
            "linear_calibration",
            common | {"weights_column": "sigma", "weights_kind": "known_sigma"},
        )
        assert math.isclose(result["slope"], 1.9239750445632797, rel_tol=1e-11)
        assert math.isclose(result["slope_standard_error"], 0.04093384079998048, rel_tol=1e-10)
        run_case("profile", "data_profile", {})
        run_case("xy-plot", "plot_xy", common)
        _, result, _ = run_case(
            "kinetics",
            "first_order_kinetics",
            {
                "initial_concentration": 2.0,
                "rate_constant": 0.25,
                "time_end": 8.0,
                "points": 101,
                "concentration_unit": "mmol/L",
                "time_unit": "s",
            },
        )
        assert math.isclose(result["final_concentration"], 2 * math.exp(-2), rel_tol=1e-6)
        figure = next(a for a in artifacts if a["role"] == "native_figure")
        run_case(
            "figure-revision",
            "revise_figure",
            {"title": "Revised synthetic calibration", "x_limits": [0.0, 5.0]},
            source_job_id=relative["job_id"],
            source_artifact_id=figure["artifact_id"],
            expected_revision=relative["job_id"],
        )
        assert digest(source) == original_hash
        evidence["original_input_preserved"] = True
        evidence["matlab"] = core.call("matlab_status", {})["backend"]
        evidence["outcome"] = "passed"
    finally:
        core.close()
        atomic_json(Path(args.output), evidence)
    print(
        "PASS: all five operations, noisy weighting, standalone rerun, native reopen and original local delivery.",
        flush=True,
    )


if __name__ == "__main__":
    main()
