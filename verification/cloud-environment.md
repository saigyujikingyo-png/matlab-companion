# MATLAB Companion cloud environment verification

Date: 2026-09-15.

Status: **READY for cloud-container setup and portable checks at `f3e1e67`; later changes require their own run**.

## Scope

This receipt covers the matching Codex Web development environment for
`saigyujikingyo-png/matlab-companion`. It does not establish native MATLAB
execution, end-user installation, a model benchmark, desktop dispatch or host
artifact delivery.

The first local native run and the real stdio protocol smoke check passed
separately. The [native receipt](native-acceptance.json) covers six synthetic
cases across five operations and local file readback. It is not a cloud
container result. [Compatibility](../docs/COMPATIBILITY.md) records GUI,
new-device, host/model and other-host acceptance as unverified.

## Saved environment

The root contributor created and read back the matching environment through
the official Codex Web interface in the intended existing account. Its
repository association is `saigyujikingyo-png/matlab-companion`.

Environment: [Chembridge / MATLAB Companion](https://chatgpt.com/codex/cloud/settings/environment/6aa97c8022048191bc6e1faa963492d8).

| Setting | Saved value |
| --- | --- |
| Container image | `universal` |
| Python selection | `3.12`; actual container runtime observed as `3.12.13` |
| Container caching | On |
| Setup | `bash scripts/setup_codex_cloud.sh` |
| Maintenance | `bash scripts/setup_codex_cloud.sh` |
| Agent network preset | Common dependencies |
| Additional documentation domains | `mathworks.com`, `www.mathworks.com`, `uk.mathworks.com` |
| Agent HTTP methods | GET, HEAD, OPTIONS |
| Environment variables and secrets | None added |

The setup script installs locked portable dependencies. It does not install
MATLAB, a licence or private datasets, and its successful exit would not by
itself establish that the product checks passed. The selected network policy
is configuration evidence, not a test of every permitted route.

## Evidence ledger

| Stage | State | Evidence and limit |
| --- | --- | --- |
| Repository discovery | READY | The public repository is selectable in the intended account. |
| Environment creation and saved settings | READY | Saved environment and repository association read back in the official UI. |
| Actual cloud-container setup | READY for tested commit | Setup and maintenance both succeeded in the Linux universal container; Python `3.12.13`. |
| Actual cloud portable checks | READY for tested commit | Tests, Ruff, contract schemas, real stdio smoke and public-file audit passed at the commit recorded below. |
| Model-based cloud task | NOT RUN | No cloud model task has been launched for this verification. |
| Desktop-to-cloud dispatch | NOT RUN | Saved Web configuration does not exercise desktop dispatch. |
| Native MATLAB and host delivery | SEPARATE | This Linux development configuration does not establish native MATLAB execution or received artifacts in a target host. |

## Actual cloud-container results

The root contributor ran the checks in the saved environment's interactive
terminal through the official Codex Web interface and read their results.
The observed `git HEAD` was
`f3e1e67b44a2e6758c762b98554b460e2744c7f6`, with Python `3.12.13` in the Linux
universal container.

| Check | Observed result |
| --- | --- |
| Setup: `bash scripts/setup_codex_cloud.sh` | Success |
| Maintenance: `bash scripts/setup_codex_cloud.sh` | Success |
| Pytest | **157 passed in 5.20 s** |
| Ruff | Passed |
| Contract/schema checker | **22 schemas passed** |
| Real stdio MCP smoke | Passed |
| Public-file audit | **33 public files passed** |

These are actual cloud-container results for that exact commit. Subsequent
core fixes and later commits are not covered by this run and must receive
their own applicable checks. No model-based cloud task or desktop-to-cloud
dispatch was performed, and no MATLAB installation or licence was added to
the container.

## Resolved discovery issue

The repository was initially absent from the picker after its first source
publication. The owner completed the existing GitHub verification, and the
root contributor confirmed the existing ChatGPT Codex Connector already used
**All repositories**, including current and future repositories. No access
change or connection reset was needed.

After integration commit `f3e1e67` was published, a repository search became
available. A read-only discovery check in another already signed-in browser
did not create an environment in that account. The root contributor then
completed creation in the intended account. No account address, credential,
cache change or application-internal repair is included in this receipt.

No unrelated environment was modified. Container execution, native execution,
installation, model benchmarks and file delivery remain independent gates.
