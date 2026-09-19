# Alpha.4 engineering package boundary

The planned package identity is `0.1.0a4` / `v0.1.0-alpha.4`. This is an unpublished engineering candidate. An existing Alpha.3 installation remains separate. No Alpha.4 tag, release, host registration, installed activation or native/scientific acceptance follows from the source version label.

The startup implementation was reviewed at `9c963a89f1d18ac3db81f8afb4b481aae744ae8b`. P1 preserves its startup, CLI, client and coordinator code and the Core/native/storage/public contracts. The package increments metadata and strengthens build and passive package admission only. A later shipped activation change requires a new complete source commit and a fresh package audit.

## One source identity per candidate

The Windows builder refuses a dirty or changing source checkout. Before wheel creation it captures the committed source identity and tracked file hashes, then copies only that snapshot into a fresh staging directory. The program wheel and public documentation come from those frozen bytes; both the original and frozen copies are checked again before completion. Each attempt retains a separate staging directory, including failed attempts.

The build records the managed CPython version and a digest of the copied clean runtime tree, the uv version, resolved build-tool versions, project wheel and actual hash-locked dependency wheels, lockfile, exported requirements, and reference-file hashes. The runtime tree digest is not an upstream Python download archive checksum. This establishes recorded inputs and readback, not a claim of bit-for-bit reproducible builds.

## Offline references and manifest

The package keeps its root documentation, tracked public docs/verification files and an explicit allowlist of 22 additional public references. Unapproved new dependencies fail the check. Ignored files, private evidence, Git state and development environments are excluded. Normative copies remain byte-identical to the frozen source. The validator checks packaged Markdown targets and local anchors, path containment and case consistency before freezing the manifest and after extraction.

Every distributed file has a relative path, size and SHA-256 entry. The manifest binds the source and build-provenance digest. The completed ZIP receives its own checksum and a private build receipt. A package audit checks malformed archives, duplicate or unlisted files, hashes, version labels, source/reference identity and bounded privacy fingerprints before executing any package command.

## Passive package verification

The exact ZIP is extracted to a fresh path containing spaces and Unicode. The audit uses only that extracted interpreter and installed module. Guards block Core construction, service admission and further child-process creation inside tested entrypoints. The audit checks the passive self-test; six-tool discovery and output schemas; status, help and schema reads; structured errors for invalid inspect/run/job requests; JSON fallback; schema resources; and Setup/Tk import with a Tcl interpreter. It creates no window and no product state root. Full file hashes and extra-file inventory are checked again afterwards.

A valid inspection or job request may enter the coordinator path, so it is excluded from this P1 audit. Package checks do not prove native execution, unknown-job recovery, real OS-event handling, current installation quiescence, model acceptance, or original-file host delivery. Those evidence and authorization gates remain separate.

## Engineering commands

Build only after committing every intended package change. Run the builder with the managed Windows x64 CPython 3.12 development environment. The audit requires the retained engineering wheel/dependency inputs next to the ZIP, the exact source commit and an explicit private report location.

```text
python scripts/build_windows_bundle.py
python tests/manual_package_audit.py --archive <candidate.zip> --expected-source <40-character-commit> --report <private-report.json>
```

These commands do not install the package or change any host configuration. Do not launch the bundled Setup against an existing installation as part of P1. Preserve old version directories and unresolved ownership/job records.
