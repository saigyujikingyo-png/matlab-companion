---
name: matlab-workflow
description: Use MATLAB Companion for bounded CSV or TSV analysis, editable MATLAB figures, linear calibration and first-order kinetics through its local MCP server.
---

# MATLAB Companion workflow

Use the `matlab-companion` MCP connection created by the setup wizard. This skill adds guidance; it does not install MATLAB or establish host acceptance.

This guidance targets the `0.1.0a4` / `0.1.0-alpha.4` unpublished packaging candidate. Startup source acceptance and package verification are separate; installed activation is not approved; R3 has not started. Discover the connected runtime's tools before using candidate features with an older installation. Do not imply this candidate is released or inherit earlier acceptance results.

1. Call `matlab_status`. This is passive and does not start the job service. Distinguish installed/unverified from actual native verification. If installation or folder permission is missing, direct the user to Start Setup.
2. Discover relevant parameters with `matlab_help`. Preserve input and explicit units. Clarify relative weights versus known standard deviations, and free versus zero intercept, when material and unspecified.
3. Inspect the selected CSV/TSV. Submit one `matlab_run` with a stable idempotency key. A job ID is acceptance of work, not completion.
4. Read `result.job.state`, `job.phase` and `job.event_seq`. Use `matlab_job` with `action="wait"`, the same `job_id`, `after_event_seq` from the last snapshot and `timeout_seconds` from 0 to 10 (default 5). The limit bounds core waiting after request receipt; service startup and transport can add time. A deadline returns a successful current snapshot, not a job failure. Compare the sequence/state before another wait; use status or a later wait after `WAIT_BUSY`. With an older runtime lacking this action, use bounded status polling. For unknown outcomes, reconcile the existing job and retain its ID. Never rerun to repair response formatting or a lost connection.
5. Read detailed results/artifacts on demand. Use validated `structuredContent`; the JSON fallback contains the same metadata. Unavailable uncertainty is not zero.
6. Deliver originals through `matlab_artifacts` and check size/hash. Set `destination` to a full file path including the original artifact filename, under the selected output folder (for example `<output folder>/figure.fig`). A read above 16 MiB returns `not_delivered` / `local_copy` instructions; use the existing deliver action rather than retrying the resource URI. A local path or embedded resource is not automatically a host attachment.
7. Report native reopen, calculation, visual review, native process exit and actual file delivery separately. Check labels/units before claiming visual acceptance. Do not infer native exit from a backend return, job phase or idle service exit. Do not inherit other build, licence, host or model acceptance.

## Client lifetime and recovery

Accepted work belongs to an on-demand coordinator for the user and resolved installation root. A client disconnect abandons its response/wait and does not cancel the scientific job. Reconnect to that root with the existing job ID or original idempotency key. Lost responses never authorize an automatic write retry. Cancellation requires an explicit `matlab_job` action; `cancel_requested` is intent, not proof of a stopped MATLAB process. Coordinator loss retains unknown/quarantine recovery without replaying a dispatched operation.

If startup is unconfirmed, retain its startup attempt identifier and existing ownership records. Later calls and Setup's Start job service observe the same pending attempt; they are not a reset or bypass. Do not delete a marker, start an older runtime, or resubmit scientific work to repair startup. Installed activation and native acceptance require separate evidence.

`job.phase` is factual: `executing` includes session startup, and `validating` means receipt/artifact checking. Neither reports a percentage. `job.event_seq` changes only when the persisted summary changes. Legacy jobs may return null phase and sequence zero; do not rewrite them to normalize a response.

## Retained storage

Status observes logical bytes under the retained job store without starting workers or deleting files. If `storage_complete` is false, retained-job and byte counts are lower bounds; `active_jobs=null` means unknown, not zero. The scan excludes installed runtimes, source folders and external delivered copies; it is not a quota or a complete disk-use report. `retention="explicit_removal_only"` and `automatic_cleanup=false` preserve originals and unknown-job evidence. There is no job-removal action in this candidate; storage observations do not authorize deletion.

## Supported operations

Operations: `data_profile`, `plot_xy`, `linear_calibration`, `first_order_kinetics`, `revise_figure`. Revision only accepts Companion-owned figures: pass the source figure's `job_id` as both `source_job_id` and `expected_revision`, plus its `artifact_id` as `source_artifact_id`. A hash is not a revision ID. General evaluation, arbitrary MAT/FIG loading and remote sharing are unavailable.
