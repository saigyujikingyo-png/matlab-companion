# MATLAB Companion contributor entrypoint

Read DEVELOPMENT_PRINCIPLES.md (shared version 2026-09-14.1), README.md and docs/IMPLEMENTATION_CONTRACT.md before work. docs/ARCHITECTURE.md contains the approved design and historical planning evidence.

Implement one host-neutral core with thin adapters. Use the official MathWorks MATLAB MCP Server as a private backend first. Scientific computation and editable files come from licensed MATLAB; portable tests do not prove native execution or host delivery. Never attach to or terminate an unrelated MATLAB session. Keep jobs, credentials, vendor binaries and runtime environments outside public source and cloud sync.

Use Python 3.12 and locked dependencies. Setup: `uv sync --locked --extra dev`. Checks: `uv run pytest -q`, `uv run python scripts/check_contracts.py`, `uv run python scripts/smoke_mcp.py`, `uv run python scripts/check_release.py`. Native checks use explicitly owned sessions and synthetic data, and are separate from portable CI. Commands under development must be labelled accurately until implemented.

All public tools require meaningful outputSchema and server-validated structuredContent; all dispatched operations require their own validated result contract. Preserve original artifacts, hashes, native reopen and separate delivery evidence. Public content is English. Ordinary users must not need a coding project or development terminal. Read the shared principles for cross-task standing authorisation and Terra max acceptance requirements.

Preserve unrelated changes. Agents own disjoint files; the root integrates and verifies the combined state. No source publication includes private inputs, licence files, tokens or installed vendor runtimes.
