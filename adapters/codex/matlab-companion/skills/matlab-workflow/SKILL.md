---
name: matlab-workflow
description: Use MATLAB Companion for bounded CSV or TSV analysis, editable MATLAB figures, linear calibration and first-order kinetics through its local MCP server.
---

# MATLAB Companion workflow

Use the `matlab-companion` MCP connection created by the setup wizard. This skill adds guidance; it does not install MATLAB or establish host acceptance.

1. Call `matlab_status`. Distinguish installed/unverified from actual native verification. If installation or folder permission is missing, direct the user to Start Setup.
2. Discover relevant parameters with `matlab_help`. Preserve input and explicit units. Clarify relative weights versus known standard deviations, and free versus zero intercept, when material and unspecified.
3. Inspect the selected CSV/TSV. Submit one `matlab_run` with a stable idempotency key. A job ID is acceptance of work, not completion.
4. Read `matlab_job` with bounded waits. For cancellation/unknown outcomes, reconcile the existing job and retain its ID. Never rerun to repair response formatting or a lost connection.
5. Read detailed results/artifacts on demand. Use validated `structuredContent`; the JSON fallback contains the same metadata. Unavailable uncertainty is not zero.
6. Deliver originals through `matlab_artifacts` and check size/hash. Set `destination` to a full file path including the original artifact filename, under the selected output folder (for example `<output folder>/figure.fig`). A local path or embedded resource is not automatically a host attachment.
7. Report native reopen, calculation, visual review and actual file delivery separately. Check labels/units before claiming visual acceptance. Do not inherit other build, licence, host or model acceptance.

Operations: `data_profile`, `plot_xy`, `linear_calibration`, `first_order_kinetics`, `revise_figure`. Revision only accepts Companion-owned figures: pass the source figure's `job_id` as both `source_job_id` and `expected_revision`, plus its `artifact_id` as `source_artifact_id`. A hash is not a revision ID. General evaluation, arbitrary MAT/FIG loading and remote sharing are unavailable.
