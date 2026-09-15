# Next-phase technical route: source notes

Research date: **2026-09-15**. Status: **planning only; implementation not started**.

These notes support the next roadmap. They record read-only source inspection
and official documentation, not new native, model, installation or cloud
acceptance. No dependency, runtime, cloud environment or connection was changed.
All external sources below were consulted on the research date. A versioned
URL identifies the reviewed revision; an unversioned page is a dated observation.

## 1. Implementation baseline

The working checkout was `a987b494ef677978f86af84210da9f667f6fa589` during
inspection. The published alpha's immutable runtime remains `c5c7317`; see
[compatibility](COMPATIBILITY.md) for its distinct package, native, model and
delivery evidence. The [architecture](ARCHITECTURE.md) is an approved historical
design, not a current implementation inventory.

Local facts from [backend.py](../src/matlab_companion/backend.py),
[core.py](../src/matlab_companion/core.py),
[server.py](../src/matlab_companion/server.py),
[pyproject.toml](../pyproject.toml) and [uv.lock](../uv.lock):

- The private native adapter pins official MATLAB MCP Server **0.13.0** and
  verifies the platform binary hash. Each execution opens a private backend
  subprocess and calls the packaged launcher through `run_matlab_file`, using
  an explicit MATLAB root, `new` session, `nodesktop` and disabled telemetry.
  It uses `ClientSession.initialize()` and a bounded native request timeout.
- The core has durable job IDs, idempotency, cross-process locks, one worker
  per core instance, a ten-active-job limit, cooperative cancel flags and
  receipt reconciliation. An uncertain native return quarantines the executor.
  A shared IPC coordinator and reusable warm MATLAB session remain planned.
- Six public tools provide validated object results, matching JSON text
  fallbacks, operation-specific schemas and original resources. Local delivery
  reads back destination hashes. Inline resources are capped at 16 MiB.
  Remote HTTP, device pairing and host attachment adapters are not implemented.
- The Python SDK is already locked to **mcp 2.2.0**. This is not a proposed
  migration from SDK v1. Existing initialize-based checks do not by themselves
  establish every feature of the newer protocol or every target host.

## 2. Official MATLAB backend and lifecycle

### Verified source facts

| Source and revision | Finding relevant to this roadmap |
| --- | --- |
| [Official release list](https://github.com/matlab/matlab-mcp-server/releases), [v0.13.0 release](https://github.com/matlab/matlab-mcp-server/releases/tag/v0.13.0), published 2026-09-03 | The page still marks 0.13.0 as Latest. Its changes concern a custom MATLAB base path and clarification of incompatible arguments for existing-session mode. No newer release was listed. |
| [Versioned README](https://github.com/matlab/matlab-mcp-server/blob/v0.13.0/README.md#arguments) | MATLAB starts lazily unless eager initialization is requested. `new` starts a session; default `auto` can attach to a shared one. Existing-session mode requires R2023a+, setup of the upstream toolbox and `shareMATLABSession()`; with multiple shared sessions the most recently shared wins. Existing mode rejects root, working-folder and display arguments. `nodesktop` does not prevent every GUI command from opening a window. |
| [Versioned usage terms](https://github.com/matlab/matlab-mcp-server/blob/v0.13.0/README.md#licensing-and-usage), [licence](https://github.com/matlab/matlab-mcp-server/blob/v0.13.0/LICENSE.md) | The upstream usage notice prohibits sharing a server among multiple users and directs centralized/shared-use questions to MathWorks. A private executor design does not establish a particular licence's remote-use entitlement. |
| [Versioned unstructured tool implementation](https://github.com/matlab/matlab-mcp-server/blob/v0.13.0/internal/adaptors/mcp/tools/basetool/withunstructuredcontent.go) | This implementation advertises no output schema and returns converted rich content. Companion's scientific contracts and file receipts remain necessary. |
| [Versioned custom-tool guide](https://github.com/matlab/matlab-mcp-server/blob/v0.13.0/guides/custom-tools.md) | Custom definitions load at startup, accept scalar argument types and return command-window output. A custom entrypoint alone does not provide durable scientific jobs or verified artifact delivery. |
| [Versioned embedded connector client](https://github.com/matlab/matlab-mcp-server/blob/v0.13.0/internal/adaptors/matlabmanager/matlabsessionclient/embeddedconnector/client.go) | Evaluation requests carry a Go request context. This source inspection supplies no native-stop acknowledgement contract. Internal connector URLs and credentials are implementation details, not a proposed integration surface. |
| [Engine cancellation](https://www.mathworks.com/help/matlab/apiref/matlab.engine.futureresult.cancel.html), [Engine limitations](https://www.mathworks.com/help/matlab/matlab_external/limitations-to-the-matlab-engine-for-python.html) | Engine's asynchronous cancellation reports whether cancellation succeeded. Engine cannot start/connect to remote MATLAB, and arrays transferred between Python and MATLAB have a 2 GB limit including supporting data. These are documented capabilities, not tests of a replacement backend. |

### Recommendation — design inference

Keep the accepted 0.13.0 backend pin. The next lifecycle increment should first
make ownership and recovery observable while retaining a new session per job.
Record the owned process/session identity, dispatch generation, native phase,
completion receipt and shutdown observation separately. An operating-system
process identity must include enough information to avoid acting on a reused
PID. Preserve the current rule that uncertain execution blocks another write.

Then evaluate an **opt-in warm session** inside one per-user coordinator, with
thin stdio front ends. This can reduce repeated startup cost, but its benefit
must be measured against the current route; it is not an established speedup.
Reuse requires a defined reset boundary for working folder, path, variables,
figures, random state and warnings, plus restoration on failure. First prove
that an unrelated open MATLAB session is untouched. Do not implement warm reuse
by selecting whichever session was most recently shared.

Specify queued cancellation, native cooperative cancellation, confirmed stop,
late completion and unknown outcome as distinct cases. A protocol timeout or
backend subprocess exit alone must not set `native_stopped=true`. Engine is a
bounded comparison option only if the official route fails an essential
ownership or stop-confirmation requirement. It is not an automatic second
backend, and switching backends must never replay an uncertain computation.

## 3. MCP version, jobs and progress

### A material update to the original planning sources

The [latest specification](https://modelcontextprotocol.io/specification/latest)
resolved to **2026-07-28** during this review. Its
[changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)
removes the connection initialization handshake and protocol HTTP sessions from
the new revision, adds per-request version/capability metadata and
`server/discover`, and moves Tasks out of the core protocol. Treat the original
architecture's 2025-11-25 links as legacy-version references.

| Area | Current official source fact | Consequence for Companion — inference |
| --- | --- | --- |
| Protocol compatibility | [Versioning, 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning) distinguishes modern per-request metadata from legacy initialize-based connections and documents interoperability. | Record the negotiated protocol and capabilities for both the public host connection and private backend connection. Keep their versions independent. Test modern discovery and the existing legacy path separately before advertising either combination. |
| Python SDK | [Tagged 2.2.0 notes](https://github.com/modelcontextprotocol/python-sdk/blob/v2.2.0/docs/whats-new.md) describe support for both protocol eras and explicitly say the new Tasks extension is not yet implemented. [Migration reference](https://py.sdk.modelcontextprotocol.io/migration/#clientsession-get-server-capabilities-replaced-by-era-neutral-accessors) distinguishes low-level `initialize()` from `discover()`. | Keep the exact lock. An installed SDK version is not proof an extension is implemented or a host uses it. Preserve explicit validation in Companion, including error branches. |
| Tasks | The [official Tasks extension](https://modelcontextprotocol.io/extensions/tasks/overview), identifier `io.modelcontextprotocol/tasks`, uses a durable handle; `tasks/get` includes terminal results, `tasks/update` supplies mid-flight input, and cancellation is cooperative. Extension support is optional and advertised through capabilities. | Retain `matlab_run` and `matlab_job` as the current durable workflow. Add a Tasks adapter only after SDK and target-host support are proven. Do not copy the old core `tasks/result` or `tasks/list` design into a current extension. |
| Progress | [Progress, 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/progress) is optional, uses a supplied active-request token, requires increasing progress values, permits an unknown total and stops when the request completes. | Persist factual native phase events, then expose them through job status. For ordinary immediately returning submissions, do not keep sending notifications against the completed submission request. A bounded wait request can emit progress during its own lifetime. |
| Cancellation | [Cancellation, 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/cancellation) distinguishes stdio notification from HTTP response-stream closure and permits work that cannot be cancelled to ignore the signal. | Separate abandoning a wait from cancelling the durable job. Keep cancellation requests idempotent and reconcile a late native receipt. Protocol cancellation cannot establish MATLAB quiescence. |

**Proposed first increment:** add compact phase/state snapshots and a bounded
wait option to the existing job interface, with suggested next-check timing.
Return on completion, meaningful state change or the wait limit. Preserve a
hard overall deadline and monotonic event sequence; do not invent percentages
for unmeasured MATLAB work. These are proposed interface additions, not present
features. Native helper phase records should be atomic, job-bound and validated
before the host sees them. A restart should read the same job rather than submit
it again.

The future Tasks adapter should map onto that same store. Its expiry must not
silently delete scientific originals. Define cancellation and retention before
mapping Companion states to extension states; an acknowledgement of intent must
not erase the record needed to establish the eventual native outcome.

## 4. Structured results and original-file delivery

[Tools, 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/server/tools#structured-content)
permits any JSON value as structured content, still requires conformity to an
advertised output schema, and recommends matching serialized JSON text for
older clients. It also recommends stable tool-list ordering. **Recommendation:**
retain the current compact object envelopes and six stable names. Broader JSON
support is not a reason to break existing consumers. Keep scientific tables and
schema detail available on demand, outside routine status responses.

[Resources, 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/server/resources)
defines text or base64 binary contents, URI identifiers, optional size/media
metadata and client-controlled use. A file-like URI need not be a physical file;
HTTPS resources are appropriate when the client can fetch them directly.

**Design inference:** a resource result is one stage of delivery, not evidence
of an attachment accepted by a host. Retain a manifest containing immutable
artifact identity, original name, media type, size and SHA-256. A host adapter
should record the receiver's supported reference plus destination readback.
Keep creation, native verification, transport and received-file status separate.
Retrying a transfer should reuse the existing bytes and never rerun MATLAB.

For files above the current inline limit, prefer an explicitly implemented
receiver transfer route with bounded streaming, authenticated retrieval and
expiry. Do not place arbitrary MAT/FIG bytes in a model prompt or expose local
paths as if they were downloadable attachments. Whether a host supports chunking,
workspace materialization or attachments remains a per-host discovery gate.

## 5. Local and remote architecture choice

The current [transport overview](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports)
defines stdio as a client-launched subprocess and Streamable HTTP as an
independent server reached with request POSTs. The new
[HTTP binding](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)
does not use the legacy GET stream, session ID or `Last-Event-ID` resumption.
Older clients require their version's behavior. Local HTTP requires Origin
validation and should bind only to loopback.

For an authenticated remote route, the
[authorization specification](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)
requires protected-resource discovery and validation that tokens are intended
for that server. It rejects token passthrough; stdio does not use this HTTP OAuth
flow. This protocol source does not grant MATLAB remote-use permission.

| Route | Proposed position | Additional acceptance required |
| --- | --- | --- |
| Local stdio and per-user coordinator | First next-phase implementation target. Keep filesystem locality and existing host adapters; isolate the coordinator lifetime from a front end disconnect. | Two simultaneous local clients, explicit ownership, restart/reconnect, idle exit, queue bounds and preservation of jobs/artifacts. |
| Optional local HTTP adapter | Add only for a host that requires it; do not make it a new default listener. | Loopback/Origin/authentication behavior, negotiated protocol compatibility and host file receipt. |
| Remote HTTPS adapter plus paired device executor | Separate later increment under the same core contracts. Proposed outbound pairing connects one user's licensed device; gateway carries authorized jobs and artifacts. No shared public native evaluator. | Actual target-host auth and file contract, pairing/revocation, user/device isolation, offline/reconnect, duplicate submission, expiry, quotas and applicable vendor permission. |
| Central MATLAB service shared across users | Excluded from this route. | Upstream directs shared/centralized use to MathWorks; do not infer permission from an HTTP wrapper. |

An HTTP request ID, protocol session, device identity and scientific job ID serve
different purposes. Keep the job/revision IDs stable across reconnects and
transport versions. This also lets a delivery failure recover independently
from native execution. Avoid relying on legacy transport session affinity to
own a MATLAB process.

## 6. Gates for the next implementation proposal

These are future checks, not checks performed for this document:

1. **Lifecycle:** cancel before dispatch, cancel during a controlled native phase,
   timeout, backend loss, coordinator restart, late receipt and an unrelated open
   MATLAB session. Confirm ownership and whether native work actually stopped.
2. **Jobs and protocol:** preserved idempotency/revisions through reconnect;
   bounded wait/progress without notification leakage; legacy and modern
   version paths; retained fallback where Tasks support is absent.
3. **Resource budget:** cold startup, useful calculation time, peak memory,
   post-job processes and idle exit. Compare warm reuse only on equivalent
   workflows after isolation/reset gates pass.
4. **Delivery:** original native and preview files through one actual additional
   host, including receiver-supported references and size/hash readback; an
   interrupted transfer retries without another scientific run.
5. **Release scope:** installation/visible setup, native lifecycle, each host/model
   and each delivery destination keep independent evidence. Existing alpha
   receipts retain their original commits and bounded claims.

Formal implementation should begin only after the next-phase roadmap is
approved. This research makes no new acceptance claim.
