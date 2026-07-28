# CPU-only installer candidate

`cpu-only.iss` packages only the validated `dist/ru-zh-subtitles-cpu` onedir.
Run `build_installer.ps1` with the expected current Git commit and the official,
validly signed Inno Setup 7.0.2 x64 compiler. The script rejects CUDA DLLs,
missing `torch_cpu.dll`, model weights, an unexpected commit, or a non-CPU
frozen runtime before compilation.

The per-user installer uses stable AppId
`8773A11B-6B74-42AF-85AF-CAD43EB946CF`, installs under LocalAppData, requires no
administrator access, and leaves the separate user model directory untouched
during uninstall. Generated setup files, manifests, build reports and logs stay
under ignored `dist/installer` or `data` paths and must not be committed.

The GPU specs remain internal development and historical benchmark artifacts.
No GPU installer is produced.
