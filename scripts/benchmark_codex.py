"""Explicit local Codex model acceptance; uses the signed-in account, never portable CI."""

import argparse
import json
import math
import shutil
import subprocess
import time
from pathlib import Path

from matlab_companion.storage import atomic_json, default_root, digest, utc_now


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", required=True, help="Packaged runtime interpreter")
    parser.add_argument("--output", default="verification/codex-benchmark.json")
    parser.add_argument(
        "--summarize-run",
        type=Path,
        help="Re-read an existing completed run without calling a model",
    )
    args = parser.parse_args()
    if args.summarize_run:
        previous = json.loads(Path(args.output).read_text())
        summarize(
            args.summarize_run, args.python, args.output, previous["exit_code"], previous["seconds"]
        )
        return
    run = default_root() / "acceptance" / ("codex-" + str(time.time_ns()))
    inputs, outputs = run / "inputs", run / "delivered"
    inputs.mkdir(parents=True)
    outputs.mkdir()
    source = inputs / "calibration.csv"
    source.write_bytes(b"concentration,absorbance\n0,1\n1,3\n2,5\n3,7\n")
    root = run / "store"
    atomic_json(
        root / "settings.json", {"allowed_roots": [str(inputs)], "output_roots": [str(outputs)]}
    )
    prompt = (
        "Use only the MATLAB Companion MCP tools for this synthetic acceptance workflow. "
        "Do not use shell tools or browse. Inspect " + str(source) + ". "
        "Fit absorbance against concentration with a free intercept, no weights, "
        "x unit mmol/L and y unit 1. Title the figure Synthetic Codex calibration. "
        "Wait for native completion. Discover detailed results as needed and deliver "
        "all original artifacts to " + str(outputs) + ", one file per artifact, using the "
        "Companion delivery tool. Then revise the owned figure title to Revised Codex calibration "
        "while preserving curves, await completion and deliver its originals under the revision "
        "subfolder. Report slope/intercept, both job IDs, native verification and actual delivery "
        "separately. Do not claim visual review or host attachment delivery. Never replay an unknown write."
    )
    command = [
        shutil.which("codex"),
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--skip-git-repo-check",
        "-C",
        str(run),
        "--sandbox",
        "read-only",
        "-m",
        "gpt-5.6-terra",
        "-c",
        'model_reasoning_effort="max"',
        "-c",
        'approval_policy="never"',
        "-c",
        "mcp_servers.matlab_companion.command=" + json.dumps(str(Path(args.python).resolve())),
        "-c",
        "mcp_servers.matlab_companion.args="
        + json.dumps(["-I", "-m", "matlab_companion", "serve", "--root", str(root)]),
        "--json",
        "-o",
        str(run / "answer.txt"),
        "-",
    ]
    print("Private model acceptance workspace:", run, flush=True)
    started = time.monotonic()
    with (
        (run / "events.jsonl").open("w", encoding="utf-8") as out,
        (run / "stderr.log").open("w", encoding="utf-8") as err,
    ):
        result = subprocess.run(
            command, input=prompt, text=True, stdout=out, stderr=err, timeout=900, check=False
        )
    summarize(
        run, args.python, args.output, result.returncode, round(time.monotonic() - started, 3)
    )


def summarize(run, runtime_python, output_path, exit_code, elapsed):
    root, outputs = run / "store", run / "delivered"
    events = [
        json.loads(line)
        for line in (run / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.startswith("{")
    ]
    jobs = [json.loads(p.read_text()) for p in (root / "jobs").glob("*/state.json")]
    completed = [
        j
        for j in jobs
        if j["state"] == "completed" and j["operation"] in {"linear_calibration", "revise_figure"}
    ]
    numerical = False
    for job in completed:
        if job["operation"] == "linear_calibration":
            details = json.loads((root / "jobs" / job["job_id"] / "result.json").read_text())
            numerical = math.isclose(details["slope"], 2.0, abs_tol=1e-10) and math.isclose(
                details["intercept"], 1.0, abs_tol=1e-10
            )
    delivery = []
    for job in completed:
        manifest = json.loads((root / "jobs" / job["job_id"] / "artifacts.json").read_text())
        artifacts = manifest if isinstance(manifest, list) else manifest.get("artifacts", [])
        target = outputs / "revision" if job["operation"] == "revise_figure" else outputs
        for a in artifacts:
            received = target / a["name"]
            delivery.append(
                {
                    "name": a["name"],
                    "operation": job["operation"],
                    "verified": received.is_file()
                    and received.stat().st_size == a["size_bytes"]
                    and digest(received) == a["sha256"],
                }
            )
    usage = [e.get("usage") for e in events if e.get("usage") is not None]
    calls = [
        e["item"]
        for e in events
        if e.get("type") == "item.completed" and e.get("item", {}).get("type") == "mcp_tool_call"
    ]
    report = {
        "observed_at": utc_now(),
        "model_requested": "gpt-5.6-terra",
        "reasoning_requested": "max",
        "host": "Codex CLI ephemeral, existing signed-in account",
        "exit_code": exit_code,
        "seconds": elapsed,
        "usage": usage or None,
        "completed_jobs": [
            {k: j[k] for k in ("job_id", "operation", "verification")} for j in completed
        ],
        "tool_call_count": len(calls),
        "extra_profile_jobs": sum(j["operation"] == "data_profile" for j in jobs),
        "delivery_readback": delivery,
        "independent_calibration_check": numerical,
        "source_commit": json.loads(
            (Path(runtime_python).resolve().parent.parent / "bundle-manifest.json").read_text()
        )["source_commit"],
        "scope": "One synthetic calibration and continued figure edit, local original files; not GUI/new-device/all-host acceptance",
    }
    report["outcome"] = (
        "passed"
        if exit_code == 0
        and len(completed) == 2
        and numerical
        and delivery
        and all(d["verified"] for d in delivery)
        else "partial"
    )
    atomic_json(Path(output_path), report)
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
