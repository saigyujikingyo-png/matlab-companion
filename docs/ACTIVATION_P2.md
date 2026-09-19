# P2 transaction primitives and isolation boundary

This source increment is not an installed upgrade implementation. The private `activation.py` module has no Setup, CLI or MCP entrypoint. Existing Setup behavior and all startup/Core/native/public code remain unchanged. P1 package evidence at source `8dc506c45e15531cbb4ca7de831fbc06b56aee3f` does not cover this module; a shipped candidate needs a new complete source identity and fresh package verification.

## What is implemented

A single transaction directory is created exclusively for one canonical root. It retains the source/package identity, reviewed before/desired target identities, optional reviewed package inventory digest, account SID/UID and volume/file identity. Immutable, bounded events are flushed and read back before a requested effect. The atomically replaced summary must match the complete hash chain. Missing events, orphan files, changed identity, invalid transitions or event/summary disagreement remain unknown. There is no reset, history cleanup or creation of a replacement transaction after an ambiguous request.

Conditional-provider operations use one operation ID. A possibly dispatched request is persisted before calling the provider. A lost response does not cause a second dispatch. Reconciliation records observed bytes in that same operation; observing either the old or desired state remains unknown without completion evidence. A third state becomes conflict and is preserved. Existing profile/shortcut/host targets are never restored automatically.

The included Codex provider always refuses conditional mutation, even if a subclass merely claims the capability. It implements no host write. Official CLI precheck plus readback is not compare-and-swap. Complete live launch-source enumeration is not accepted or implemented in this increment, so the default external snapshot explicitly reports incomplete visibility. Successful external inventories in tests come from clearly labelled fake providers; they do not establish live Windows/Codex coverage.

## Two-pass admission and locks

The actual lock order is `.activation.lock`, `.setup-codex.lock`, then nonblocking probes of `.coordinator-start.lock`, `.coordinator.lock` and `.execution.lock`. Every acquisition uses timeout zero and releases in reverse order; no UI wait or automatic service start occurs. The existing coordinator holds lifetime before startup, so the inverse startup/lifetime observation never waits. A busy ownership probe refuses immediately. Coordination lock files may be created in the selected test root; metadata observations do not rewrite product settings or jobs.

Two complete metadata and external inventory observations must agree within one bounded deadline. Metadata covers the root settings/index/ownership records, all bounded job summaries and selected dispatch/native metadata, and all registered-input metadata. Native receipts and backend responses are checked for presence only and require separate review, because they may contain scientific results. Their contents and scientific payloads are not opened. Counts/bytes/deadline exhaustion, missing summaries, unknown directories, inaccessible identities, root aliases/reparse points, duplicate or unrecognized external launch sources, live owners and incomplete declared coverage all refuse admission. Directory entry identities use fresh lstat because Windows cached directory enumeration may omit link counts and file IDs.

Default bounds are 10,000 jobs/input records, 256 launch sources, 4,096 process identities, 64 MiB selected metadata and a five-second observation deadline. Each selected metadata/event file is limited to 64 KiB; journals stop at 128 events. The full external adapter must honor its own deadline and prove coverage before a live acceptance claim is possible.

Current admission deliberately refuses any retained coordinator/startup ownership marker and any historical job dispatch/native-session metadata, including a completed summary. It does not interpret those records as fresh retirement evidence. Future terminal/native-exit interpretation requires separate review. Unknown or active jobs are never reconciled, altered or replayed here. A process/metadata snapshot and cooperative locks cannot exclude someone manually launching an old executable later.

## Staging is available only in fresh temporary test roots

The factory creates a new directory under the operating system temporary directory and issues a process-local capability bound to that exact root identity. It cannot bless an existing installed root or be retargeted by changing the returned fields. Exclusive staging requires both fresh admission and the package inventory digest frozen in the review. File size/hash and complete inventory checks run before and after copying. The candidate directory and each file are created exclusively; an existing destination is preserved.

An interrupted or partial copy remains in place with the same operation ID. A new call cannot repair, overwrite or repeat it. A restart can only record read-only reconciliation. The temporary-root factory does not delete retained evidence automatically; the separately owned test fixture controls its later cleanup. Package limits are 10,000 files, 20,000 enumerated tree entries, 512 MiB per file and 2 GiB total, with bounded copy reads.

## Acceptance boundaries

Focused tests exercise actual local file locks, fake conditional providers, concurrent external edits, incomplete/two-pass scans, event/summary crashes, root identity/refusal, partial staging and same-operation recovery. They do not run Core, MATLAB, a real host mutation, a production activation, unknown-job reconciliation or OS shutdown events.

No live launch-source adapter, real conditional host provider, installed staging, UI activation, commit/rollback workflow or terminal native-exit interpretation is advertised as complete. The current transaction phases stop at staged verification or observed fake-provider mutation; later activation/passive-registered acceptance remains separately gated. No P2 module is imported by ordinary use until an accepted integration changes that explicitly.
