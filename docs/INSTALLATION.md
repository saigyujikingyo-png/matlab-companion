# Installation and recovery

MATLAB Companion is an independent Chembridge plugin. MATLAB and its valid licence must already be available separately. This development preview has a graphical setup implementation; package checks, an actual new-user installation, native execution and agent acceptance remain separate evidence in the release records.

## Windows package

Use the Windows preview package in [GitHub Releases](https://github.com/saigyujikingyo-png/matlab-companion/releases):

1. Download the Windows x64 ZIP and verify the published package checksum.
2. Extract the complete folder to a local location where it can remain after setup. Do not run from inside the ZIP or move the runtime after connecting your agent.
3. Double-click **Start Setup.vbs**. The package includes Python and Tk; ordinary users do not need to install Python, Git or a development environment.
4. Choose an **Input folder**, an **Output folder**, and the **MATLAB installation** folder containing `bin/matlab.exe`.
5. Select **Save folders**, then **Install / verify backend**. Setup acquires the pinned official MathWorks MATLAB MCP Server release, verifies its SHA-256, and reuses an existing verified copy.
6. Select **Check setup** to check the saved folders, backend checksum and installation path. This check does not launch MATLAB or verify a licence, calculation or delivered file.
7. Select **Save and connect Codex** when the official Codex executable is installed. Setup creates the named connection through the supported Codex CLI and reads it back. Open a new Codex task to check tool discovery and request a synthetic example.

If Windows Script Host is disabled by your organisation, the VBS launcher is not an accepted route on that device. Record that installation gap; do not change organisation policy to bypass it. This preview does not yet provide a signed native installer, automatic updates or a store-hosted installation.

The setup window runs downloads and CLI operations in a background worker. Its buttons are temporarily disabled while an operation is running; the window continues processing events. Wait for its result before closing the window. Closing during a connection change can leave an uncertain result; setup keeps a recovery record and checks the existing connection before another action.

## Files and saved settings

Private runtime state defaults to `%LOCALAPPDATA%\Chembridge\MATLABCompanion` on Windows. The source checkout, installed runtime, active jobs and credentials do not belong in a cloud-synchronised repository. User-selected input and output folders can be separate from the application runtime; university OneDrive is not required.

Setup retains existing valid folder selections, adds newly selected authorisations without dropping previous folders, and preserves unrelated settings. Repeating a save with the same values does not rewrite settings. Before a changed save, it retains a private recovery copy. Invalid or unreadable settings are preserved rather than replaced with empty defaults.

The selected MATLAB installation is saved as `matlab_root`. An explicit `MATLAB_COMPANION_MATLAB_ROOT` environment override takes precedence; remove or update that override deliberately if it points to an older installation. Selecting a folder establishes where MATLAB is installed; it does not establish licence validity or toolbox entitlement.

## Existing Codex connections and removal

Setup manages only the `matlab-companion` entry. It uses the installation's Python executable and the supported `codex mcp add` interface; users do not need to edit JSON or TOML. Other plugins and account configuration remain under the host's own management.

- An existing matching connection is reused.
- An existing entry with different settings is displayed and preserved. Review it in Codex before intentionally replacing it; setup does not silently overwrite it.
- A new connection gets a private `codex-connection.json` recovery record before the CLI change. A nonzero exit or unexpected readback is recorded as uncertain; setup does not automatically repeat the write or remove the entry.
- **Undo this Codex connection** removes only a connection created by this setup whose entire observed configuration still matches its saved fingerprint. Changed commands, environment, host options or disabled states prevent removal. Research files and other plugins are retained.

Avoid editing the same Codex entry concurrently with a setup action. The supported CLI does not offer an atomic conditional add/remove operation; setup performs a precheck and readback and uses its own lock to prevent simultaneous setup writers. Do not treat connection readback as a real model invocation or file-delivery test.

The preview requires the official Codex executable. Setup checks PATH, then the official Windows desktop app's local CLI directory when Explorer has no Codex PATH entry. Shell-script wrappers are not used by the graphical connector. Other compatible hosts can use the same core, but their graphical connection and original-file delivery adapters need separate implementation and acceptance.

## Executor recovery

In alpha.3, accepted jobs belong to one local coordinator for the resolved
installation root. The usual idle lifetime is 30 seconds. Disconnecting an agent
does not request cancellation. Reconnect with the same job ID and idempotency
key; explicitly request cancellation only when intended.

For the published Alpha.3 package, if a Windows host blocks independent process startup, open setup and select
**Start job service**, then return to the agent within five minutes. This explicit
action can resume accepted, undispatched work. A setup status check remains
passive. The launcher never substitutes a client-owned child after a rejected
breakaway request. Closing the whole host, outer Windows Job or operating system
is outside the individual-client lifetime guarantee.

An idle service preserves all jobs and scientific files. Storage observations
are bounded, passive counts; an incomplete scan reports lower bounds and unknown
active count. There is no automatic expiry or new job-deletion action.

An interrupted or unconfirmed native execution can place the executor in quarantine. This blocks another calculation while the original session's outcome remains uncertain.

1. Read the job ID and reason shown in **Executor recovery**.
2. Reconcile the existing job and verify that the MATLAB session owned by that job has stopped. Do not terminate an unrelated MATLAB session.
3. Tick **I verified that the displayed job's owned MATLAB session has stopped** only after establishing that fact.
4. Select **Clear this executor quarantine**.

Setup never terminates MATLAB. It checks that no executor/recovery lock is held and that the displayed quarantine marker has not changed, then writes a recovery receipt. If a crash left an active-executor marker, that marker must identify the same job and remain unchanged; it is preserved in the receipt before both matching markers are removed. Existing jobs, original inputs, artifacts and native receipts remain intact. A changed marker, different active job or busy executor prevents clearing. Clearing quarantine is not proof that a previous operation succeeded and does not authorise replaying its write; reconcile the original job first.

R1 records a coordinator instance UUID and process creation identity separately
from `native-session.json`, which observes the owned MATLAB session and its PID
when the documented API is available. Neither a PID nor a session record proves
native exit. Legacy or inaccessible coordinator identities are treated
conservatively while their process may still exist.

R2 additionally records `native-lifecycle.json`: launcher nonce and process birth
identity are verified before holding a query-only process handle until its exit.
`native_exited`, RPC response, backend return and a scientific receipt remain
separate observations. An idle coordinator exit never asserts a native stop.

## Development installation

Source development remains a separate route requiring Python 3.12 and `uv`:

```powershell
uv sync --locked --extra dev
uv run python -m matlab_companion setup
```

This route requires a coding checkout and development terminal. The window identifies it as a development installation and the connection depends on keeping that checkout/environment. It is not described as one-click ordinary-user installation.

Some development Python distributions omit Tk. Use a complete development Python/Tk installation or the tested complete Windows package. Importing the setup module and running its portable tests do not require creating a Tk window.

In R1 (`0.1.0a2`), `Run Self Test.cmd`, CLI `status` and setup's **Check setup**
use passive observations. They do not construct a coordinator, resume queued
jobs, start a worker or create a missing runtime directory. CLI `--root` reaches
setup and every execution/configuration component. Only ordinary service startup
can recover a previously accepted, undispatched queue under the existing
idempotency policy. The older `0.1.0a1` diagnostic side effect remains documented
in the [historical alpha review](ALPHA_REVIEW_2026-09-15.md).

### Unreleased startup ownership candidate

The source candidate following 34e2cf17 adds durable startup ownership. An error
that includes a **startup attempt** identifier preserves that same attempt across
later calls, including **Start job service**. Setup is not a bypass for unresolved
startup ownership. Retain the identifier and existing records for diagnosis;
there is no startup reset, expiry or instruction to delete a marker. A late
coordinator can still claim its original attempt and become ready.

This change has not been installed or packaged as an upgrade to Alpha.3. The
source version remains 0.1.0a3 for review only; do not replace that installed
version's files in place. A distinct-version candidate and verified quiescent
activation are required before deployment. Old installed frontends do not
participate in the new journal, so source tests cannot prove mixed-version
one-spawn behavior. See the [lifecycle record](LIFECYCLE.md) for the separate gates.

## Verification status

The alpha.1 setup suite recorded **16 passing Windows tests** using real temporary filesystem state and a stateful fake at the Codex process boundary. R1 adds diagnostic and root-isolation regressions plus matched active-marker recovery checks; current results are tracked in [R1 acceptance](R1_RELIABILITY.md). The Windows-specific CLI discovery case is skipped on Linux.

A separate read-only probe discovered the installed official CLI with PATH discovery disabled and returned `codex-cli 0.154.0-alpha.6.2`. This establishes CLI discovery on the development device, not an accepted visible connection setup.

These tests do not invoke the user's Codex connection commands, download the vendor binary, launch the GUI, start MATLAB or stop any process. Packaged runtime checks, visible GUI use, backend acquisition, native workflows, existing-configuration acceptance and each host/model/file-delivery result require their own evidence; these tests do not establish those outcomes.

On 2026-09-15 the current-device installation separately verified the original
package files, official backend, actual Codex connection creation/readback and
repeated connection reuse. Pre-existing MCP and marketplace entries were
preserved. The personal plugin is enabled with the designed icon; the Start-menu
entry is **Chembridge / MATLAB Companion**. Start a new Codex task to pick up the
installed skill and tools. This is a pickup instruction, not a claim that this
conversation dynamically acquired them.

The installed command completed a synthetic kinetics job and seven-file local
readback. The earlier installation probe itself had a response-parsing error,
closed its client and left a dispatched job unknown. That record was preserved
without replay; recovery checks established process absence before clearing
quarantine. Both observations are retained in the
[installation receipt](../verification/local-installation-2026-09-15.json).
The visible wizard, a fresh device, upgrade/removal and a fresh model invocation
after this installation remain separate acceptance work.
