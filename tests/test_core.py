import asyncio
from pathlib import Path

from matlab_companion.core import Core
from matlab_companion.storage import atomic_json, read_json, utc_now


class ProfileBackend:
    calls = 0

    def available(self):
        return True

    async def execute(self, job):
        self.calls += 1
        request = read_json(job / "request.json")
        await asyncio.sleep(0.03)
        (job / "outputs" / "profile.csv").write_bytes(b"rows\n2\n")
        for name in ("input.csv", "analysis.mat", "method.json"):
            (job / "outputs" / name).write_bytes(b"synthetic backend fixture")
        atomic_json(
            job / "receipt.json",
            {
                "contract_version": "1.0",
                "job_id": request["job_id"],
                "operation": "data_profile",
                "state": "completed",
                "observed_at": utc_now(),
                "matlab_version": "test-double",
                "matlab_release": "test-double",
                "summary": "Two rows profiled",
                "metrics": [],
                "artifacts": [
                    {"name": "profile.csv", "role": "data_export", "media_type": "text/csv"},
                    {"name": "input.csv", "role": "original_input", "media_type": "text/csv"},
                    {
                        "name": "analysis.mat",
                        "role": "native_data",
                        "media_type": "application/x-matlab-data",
                    },
                    {"name": "method.json", "role": "method", "media_type": "application/json"},
                ],
                "verification": {"native_reopen": True, "numerical": False, "script_rerun": False},
                "details": {"rows": 2, "columns": []},
                "error": None,
            },
        )


def setup_core(tmp_path, backend=None):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    source = inputs / "experiment.csv"
    source.write_text("concentration,absorbance\n1,3\n2,5\n", encoding="utf-8")
    return Core(
        tmp_path / "store", [inputs], [tmp_path / "delivered"], backend or ProfileBackend()
    ), source


def test_inspection_does_not_authorise_unselected_roots(tmp_path):
    core, source = setup_core(tmp_path)
    outside = tmp_path / "private.csv"
    outside.write_text("private\n1\n")
    assert core.call("matlab_inspect", {"path": str(source)})["ok"]
    rejected = core.call("matlab_inspect", {"path": str(outside)})
    assert not rejected["ok"]
    assert rejected["error"]["code"] == "INPUT_INVALID"
    core.close()


def test_duplicate_request_executes_once_and_delivery_preserves_bytes(tmp_path):
    backend = ProfileBackend()
    core, source = setup_core(tmp_path, backend)
    inspected = core.call("matlab_inspect", {"path": str(source)})
    args = {
        "operation": "data_profile",
        "input_id": inspected["input"]["input_id"],
        "parameters": {},
        "idempotency_key": "same-experiment",
    }
    first = core.call("matlab_run", args)
    duplicate = core.call("matlab_run", args)
    assert first["ok"], first
    assert first["job_id"] == duplicate["job_id"]
    core.wait(first["job_id"], timeout=5)
    assert backend.calls == 1
    listed = core.call("matlab_artifacts", {"job_id": first["job_id"]})
    artifact = listed["artifacts"][0]
    delivered = core.call(
        "matlab_artifacts",
        {
            "job_id": first["job_id"],
            "action": "deliver",
            "artifact_id": artifact["artifact_id"],
            "destination": str(tmp_path / "delivered" / "result.csv"),
        },
    )
    assert delivered["delivery"]["state"] == "verified", delivered
    assert delivered["delivery"]["sha256"] == artifact["sha256"]
    assert Path(delivered["delivery"]["destination"]).read_bytes() == b"rows\n2\n"
    core.close()


def test_malformed_receipt_keeps_job_identity_and_does_not_replay(tmp_path):
    class BadBackend(ProfileBackend):
        async def execute(self, job):
            self.calls += 1
            atomic_json(job / "receipt.json", {"state": "completed"})

    backend = BadBackend()
    core, source = setup_core(tmp_path, backend)
    inp = core.call("matlab_inspect", {"path": str(source)})["input"]["input_id"]
    args = {
        "operation": "data_profile",
        "input_id": inp,
        "parameters": {},
        "idempotency_key": "bad",
    }
    accepted = core.call("matlab_run", args)
    state = core.wait(accepted["job_id"], timeout=5)
    assert state["state"] == "unknown"
    assert state["error"]["code"] == "OUTPUT_CONTRACT_INVALID"
    again = core.call("matlab_run", args)
    assert again["job_id"] == accepted["job_id"]
    assert backend.calls == 1
    core.close()
