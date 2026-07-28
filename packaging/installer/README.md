# CPU-only installer candidate

`cpu-only.iss` packages only the validated `dist/ru-zh-subtitles-cpu` onedir.
Run `build_installer.ps1` with the expected current Git commit and the official,
validly signed Inno Setup 7.0.2 x64 compiler. The script rejects CUDA DLLs,
missing `torch_cpu.dll`, model weights, an unexpected commit, or a non-CPU
frozen runtime before compilation.

The repository must be completely clean according to
`git status --porcelain=v1 --untracked-files=all`; correctly ignored build,
dist, data, model, log, and virtual-environment paths do not count. The CPU
onedir must contain top-level `CPU_BUILD_METADATA.json` whose version, clean
lowercase Git SHA, CPU family, Windows x64 platform, and spec match the current
repository and `ExpectedCommit`. The resulting `RELEASE_METADATA.json` embeds
the validated CPU provenance and includes it in the full relative SHA manifest.

All validation, doctor, metadata, ISCC, hashing, signature inspection, report,
and log work occurs inside one unique temporary output directory. Any failure
removes the same-version setup and its companion metadata/report/log. Success
publishes metadata, log, and report before setup; setup is deliberately the
last success marker. Test injection is default-off, restricted to a system-temp
Git repository without an `origin`, and never skips CPU policy or provenance.

The per-user installer uses stable AppId
`8773A11B-6B74-42AF-85AF-CAD43EB946CF`, installs under LocalAppData, requires no
administrator access, and leaves the separate user model directory untouched
during uninstall. Generated setup files, manifests, build reports and logs stay
under ignored `dist/installer` or `data` paths and must not be committed.

`cpu-only.iss` consumes the CPU onedir recursively and adds only
`RELEASE_METADATA.json` separately. README, third-party notices, and model setup
instructions are not sourced a second time; installed copies therefore retain
the SHA values recorded in the CPU manifest.

The GPU specs remain internal development and historical benchmark artifacts.
No GPU installer is produced.
