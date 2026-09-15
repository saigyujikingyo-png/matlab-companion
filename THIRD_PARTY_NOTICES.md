# Third-party notices

MATLAB Companion's original source is MIT-licensed. MATLAB and the official MathWorks MCP server are separate products with separate terms. MATLAB Companion is an independent project and is not endorsed by MathWorks or the University of Edinburgh.

## MathWorks software

MATLAB must be installed and licensed by its user. It is never bundled here. Setup downloads the pinned official MATLAB MCP Server v0.13.0 to the user's local application-data folder, verifies the pinned SHA-256 and retains its original `LICENSE-MathWorks.md`. That server's restricted MathWorks-product terms are not replaced by this project's MIT licence. The service is single-user; do not expose it as a shared remote MATLAB service.

Source and terms: [official MATLAB MCP Server](https://github.com/matlab/matlab-mcp-server/tree/v0.13.0), [upstream licence](https://github.com/matlab/matlab-mcp-server/blob/v0.13.0/LICENSE.md).

## Windows portable runtime

The preview bundle contains a clean CPython 3.12 runtime distributed through Astral's python-build-standalone tooling. Its licence is retained in `runtime/LICENSE.txt`; Tcl/Tk and runtime component notices remain in their original directories. Dependency versions and hashes are recorded in `requirements.txt`, with each installed distribution's licence metadata retained under `runtime/Lib/site-packages/*.dist-info`. The bundle manifest records materialized file hashes. Build scripts never copy the developer virtual environment.

The MCP SDK, Pydantic and their locked transitive dependencies remain subject to their respective licences. Review the bundled notices before redistribution. Private MATLAB licence files, account credentials, user data and the MathWorks executable are excluded from public source and this bundle.
