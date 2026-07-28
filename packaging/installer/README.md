# Self-contained CPU offline installer

`cpu-only.iss` combines the provenance-bound `dist/ru-zh-subtitles-cpu` onedir
with a separately verified model bundle. Invoke `build_installer.ps1` with the
clean current Git commit, official signed Inno Setup 7.0.2 x64 compiler, and the
mandatory `-ModelAssetsRoot` argument. Omitting the bundle is an error; there is
no user-cache or network fallback.

Before ISCC runs, `packaging/model_bundle.py` validates the manifest identity,
fixed revisions, strict 40-byte newline-free refs, file set, sizes and SHA-256
of every model asset. It rejects absolute/traversal paths, links and extras, and
creates path-free `MODEL_BUNDLE_METADATA.json`. Release metadata records the
bundle and declares `self_contained=true` and `offline_ready=true`.

The repository and CPU provenance must match `ExpectedCommit` and be clean.
Validation, metadata, compilation, hashing and reports are transactional. Any
failure removes same-version offline outputs. Success publishes metadata, log,
report, `README_INSTALL.txt`, optional native Inno `.bin` slices, and finally
`setup.exe` as the success marker.

The installer:

- keeps AppId `{8773A11B-6B74-42AF-85AF-CAD43EB946CF}`;
- requires no elevation and installs the app under LocalAppData;
- installs models under `%LOCALAPPDATA%\ru-zh-live-subtitles\models`;
- requires at least 8 GiB free before starting;
- launches `live-overlay --translation-device cpu --offline --no-auto-start`;
- preserves model assets during uninstall;
- is intentionally unsigned.

Output is ignored under `dist/installer-offline`. A maximum-compression
preflight produced a single 1,762,415,746-byte setup. The builder still checks
the formal output: if it reaches 3.8 GB, it recompiles with native Inno disk
spanning and all generated files must remain together. The older
`dist/installer` model-less setup is historical and is not the teacher delivery.

Generated setups, `.bin` slices, manifests, reports, logs, CPU dist, model
weights and staging must never be committed. No GPU installer is produced.
