# MATLAB Companion

An independent Chembridge plugin for reproducible MATLAB analysis, editable native artifacts and natural-language agent workflows.

**Status: initial development.** No end-user or cross-host release is accepted yet. MATLAB remains a separately installed, legally licensed dependency. This project is not affiliated with MathWorks or the University of Edinburgh.

Read [development principles](DEVELOPMENT_PRINCIPLES.md), [architecture](docs/ARCHITECTURE.md) and [implementation contract](docs/IMPLEMENTATION_CONTRACT.md). Native execution, portable checks, installation, model calls and host file delivery have separate evidence.

Development uses Python 3.12 and the dependency lock. The core will reuse the official MATLAB MCP Server as a private execution backend and expose validated scientific workflows and original-file delivery.
