# MATLAB Companion cloud environment verification

Date: 2026-09-15.

Status: **PARTIAL — new repository not yet visible in the Codex picker**.

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

## Observed preparation

- The existing Codex Web account was signed in and the environment creation
  form was available through the supported browser interface.
- The existing GitHub organisation `saigyujikingyo-png` was available.
- The form offered the universal image, Python 3.12, container caching,
  manual setup and maintenance scripts, agent network controls and an
  interactive terminal.
- A new unsaved form was prepared for `Chembridge / MATLAB Companion`, with
  `bash scripts/setup_codex_cloud.sh` for setup and maintenance,
  common-dependencies agent network access restricted to GET, HEAD and
  OPTIONS, and additional official documentation domains `mathworks.com`,
  `www.mathworks.com`, `uk.mathworks.com`.

## Outstanding

- The product repository was published separately, but the Codex Web picker
  did not show `matlab-companion` after an ordinary refresh and reopening the
  creation form. The existing organisation and earlier repositories were
  visible. A fresh browser tab also showed another newly created product
  repository, while `matlab-companion` remained absent.
- The official GitHub installation-settings page initially required owner
  sudo authentication. After the owner completed verification, the root
  contributor read back **All repositories** for the existing ChatGPT Codex
  Connector, covering current and future repositories. Save was disabled and
  no permission change was made. Selected-repository omission is therefore
  not supported by this evidence; the remaining discovery cause is unknown.
- Select the new repository when the existing Codex connection lists it,
  save the environment and read back its settings.
- Run the actual portable checks in the cloud container and record source
  commit, Python version and output.

The official creation form, organisation menu and connector settings expose
no separate repository-refresh control. Connector settings report the
existing GitHub account as connected and offer disconnect or installation
settings; neither was used to reset the connection. Further discovery should
use the normal picker after the next source publication, without changing
permissions, caches or application internals.

No account connection, secret, licence, private dataset or unrelated
environment was changed. The prepared form was discarded during repository
discovery refresh; no environment has been saved and no cloud-container check
has run. This is not an environment-creation or cloud-container pass.
