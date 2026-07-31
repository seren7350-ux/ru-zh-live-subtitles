# Self-contained CPU offline installer 0.2.0

`cpu-only.iss` combines the provenance-bound `dist/ru-zh-subtitles-cpu` onedir
with one explicit, fully verified model bundle. Version 0.2.0 contains only the
required Silero VAD 6.2.1, official `ai-sage/GigaAM-Multilingual` `large_ctc`,
and NLLB snapshots. Legacy RNNT weights are excluded.

Invoke `build_installer.ps1` from a clean tracked commit with the official signed
Inno Setup 7.0.2 x64 compiler and mandatory `-ModelAssetsRoot`. Omitting the
bundle is an error; there is no cache discovery, download, or network fallback.
The default output is the version-isolated `dist/installer-offline-0.2.0`, so the
retained 0.1.0 course installer under `dist/installer-offline` is not overwritten.

Before ISCC, `packaging/model_bundle.py` validates identities, variant, immutable
revisions, strict 40-byte refs, exact file sets and sizes, every manifest SHA,
and fixed official GigaAM/Silero SHA values. Symbolic links, junctions and other
reparse points are rejected; ordinary NTFS hard links are accepted only as
regular files and their content is fully rehashed. Generated bundle metadata is
path-free and declares `self_contained=true` and `offline_ready=true`.

Every release attachment must be smaller than 2,000,000,000 bytes. The builder
uses native Inno disk spanning when the uncompressed inputs predict the limit,
when `-ForceDiskSpanning` is supplied, or when a single compiled setup reaches
the limit. `DiskSliceSize` is 1,900,000,000 bytes. It never implements custom
splitting. `SHA256SUMS.txt` covers setup and every `.bin`; all slices must remain
beside setup. Setup is published last and is the transaction success marker.

The installer keeps AppId `{8773A11B-6B74-42AF-85AF-CAD43EB946CF}`, installs
per user without elevation, uses CPU-only Torch, and requires at least 12 GiB
free space. The minimum system RAM is 8 GiB and 16 GiB is recommended. It is
unsigned and intended only for non-commercial course work.

Example:

```powershell
.\packaging\installer\build_installer.ps1 `
  -ExpectedCommit (git rev-parse HEAD) `
  -CpuDist .\dist\ru-zh-subtitles-cpu `
  -ModelAssetsRoot <verified-model-assets> `
  -OutputDir .\dist\installer-offline-0.2.0 `
  -ReleaseAssetLimitBytes 2000000000 `
  -IsccPath "$env:LOCALAPPDATA\Programs\Inno Setup 7\ISCC.exe"
```

Generated setup files, slices, reports, hashes, model weights and staging remain
ignored. No GPU installer, signing operation, VMware run, or GitHub Release is
part of this build stage.
