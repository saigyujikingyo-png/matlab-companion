"""Explicit licensed-native TSV regression; never part of portable CI."""

from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

from matlab_companion.core import Core
from matlab_companion.storage import atomic_json, default_root, digest, read_json, utc_now


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="verification/native-tsv-acceptance.json")
    args = parser.parse_args()
    run_root = default_root() / "acceptance" / f"tsv-{time.time_ns()}"
    inputs = run_root / "fixtures"
    delivered = run_root / "delivered"
    inputs.mkdir(parents=True)
    source = inputs / "calibration.tsv"
    source.write_text(
        "concentration\tabsorbance\tnote\n"
        '0\t1\t"sample, A"\n'
        '1\t3\t"sample, B"\n'
        '2\t5\t"sample, C"\n'
        '3\t7\t"sample, D"\n',
        encoding="utf-8",
        newline="\n",
    )
    original_hash = digest(source)
    evidence = {
        "scope": "Synthetic TSV native execution, native reopen, standalone rerun and original local-copy readback; not host/model or installer acceptance",
        "observed_at": utc_now(),
        "outcome": "incomplete",
        "input_sha256": original_hash,
        "input_size_bytes": source.stat().st_size,
        "operation": "linear_calibration",
    }
    core = Core(run_root / "store", [inputs], [delivered])
    print("Native TSV workspace:", run_root, flush=True)
    started = time.monotonic()
    try:
        inspected = core.call("matlab_inspect", {"path": str(source)})
        assert inspected["ok"], inspected
        assert inspected["input"]["media_type"] == "text/tab-separated-values"
        accepted = core.call(
            "matlab_run",
            {
                "operation": "linear_calibration",
                "input_id": inspected["input"]["input_id"],
                "idempotency_key": "explicit-tab-delimiter-and-preserved-extension",
                "parameters": {
                    "x_column": "concentration",
                    "y_column": "absorbance",
                    "x_unit": "mmol/L",
                    "y_unit": "1",
                    "title": "Synthetic TSV calibration",
                },
            },
        )
        assert accepted["ok"], accepted
        evidence["job_id"] = accepted["job_id"]
        state = core.wait(accepted["job_id"], timeout=360)
        evidence["state"] = state["state"]
        evidence["verification"] = state["verification"]
        assert state["state"] == "completed", state
        assert state["verification"] == {
            "native_reopen": True,
            "numerical": True,
            "script_rerun": True,
        }
        result = core.result(accepted["job_id"])
        evidence["result"] = result
        assert result["rows"] == 4
        assert math.isclose(result["slope"], 2.0, rel_tol=1e-12)
        assert math.isclose(result["intercept"], 1.0, rel_tol=1e-12)
        listed = core.call("matlab_artifacts", {"job_id": accepted["job_id"]})
        assert listed["ok"], listed
        artifacts = listed["artifacts"]
        original = next(item for item in artifacts if item["role"] == "original_input")
        assert original["name"] == "input.tsv"
        assert original["media_type"] == "text/tab-separated-values"
        assert original["sha256"] == original_hash
        for artifact in artifacts:
            copied = core.call(
                "matlab_artifacts",
                {
                    "job_id": accepted["job_id"],
                    "action": "deliver",
                    "artifact_id": artifact["artifact_id"],
                    "destination": str(delivered / artifact["name"]),
                },
            )
            assert copied["ok"] and copied["delivery"]["state"] == "verified", copied
        method = read_json(delivered / "method.json")
        assert method["request"]["input_path"] == "input.tsv"
        assert (delivered / "input.tsv").read_bytes() == source.read_bytes()
        job = core._job_path(accepted["job_id"])
        receipt = read_json(job / "receipt.json")
        evidence["matlab_version"] = receipt["matlab_version"]
        evidence["matlab_release"] = receipt["matlab_release"]
        evidence["artifacts"] = [
            {key: item[key] for key in ("name", "media_type", "size_bytes", "sha256", "role")}
            for item in artifacts
        ]
        evidence["original_input_preserved"] = digest(source) == original_hash
        evidence["local_delivery_readback"] = True
        evidence["method_references_preserved_tsv"] = True
        kinetics = core.call(
            "matlab_run",
            {
                "operation": "first_order_kinetics",
                "idempotency_key": "explicit-light-style-kinetics",
                "parameters": {
                    "initial_concentration": 2.0,
                    "rate_constant": 0.25,
                    "time_end": 8.0,
                    "points": 101,
                    "concentration_unit": "mmol/L",
                    "time_unit": "s",
                    "title": "Synthetic first-order decay",
                },
            },
        )
        assert kinetics["ok"], kinetics
        kinetic_state = core.wait(kinetics["job_id"], timeout=360)
        assert kinetic_state["state"] == "completed", kinetic_state
        kinetic_result = core.result(kinetics["job_id"])
        assert math.isclose(
            kinetic_result["final_concentration"], 2.0 * math.exp(-2.0), rel_tol=1e-6
        )
        kinetic_artifacts = core.call("matlab_artifacts", {"job_id": kinetics["job_id"]})[
            "artifacts"
        ]
        for artifact in kinetic_artifacts:
            copied = core.call(
                "matlab_artifacts",
                {
                    "job_id": kinetics["job_id"],
                    "action": "deliver",
                    "artifact_id": artifact["artifact_id"],
                    "destination": str(delivered / "kinetics" / artifact["name"]),
                },
            )
            assert copied["ok"] and copied["delivery"]["state"] == "verified", copied
        evidence["kinetics_light_style"] = {
            "job_id": kinetics["job_id"],
            "verification": kinetic_state["verification"],
            "result": kinetic_result,
            "local_delivery_readback": True,
            "artifacts": [
                {key: item[key] for key in ("name", "media_type", "size_bytes", "sha256", "role")}
                for item in kinetic_artifacts
            ],
        }
        evidence["outcome"] = "passed"
        print(
            "PASS: TSV and kinetics, numerical checks, native reopen, standalone rerun and original delivery.",
            flush=True,
        )
        print("TSV preview:", delivered / "figure.png", flush=True)
        print("Kinetics preview:", delivered / "kinetics" / "figure.png", flush=True)
    finally:
        core.close()
        evidence["seconds"] = round(time.monotonic() - started, 3)
        atomic_json(Path(args.output), evidence)


if __name__ == "__main__":
    main()
