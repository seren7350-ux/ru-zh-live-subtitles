# Self-contained CPU offline installer 0.2.0

This unsigned per-user course installer combines a provenance-bound CPU onedir
with all required offline models. It needs no Python, administrator rights,
network access, token, repository checkout, or manual model copy. It is for
non-commercial course use and is not a production or clean-machine claim.

## Contract

- AppId: `{8773A11B-6B74-42AF-85AF-CAD43EB946CF}` (unchanged);
- app: `%LOCALAPPDATA%\Programs\RuZhLiveSubtitles`;
- models: `%LOCALAPPDATA%\ru-zh-live-subtitles\models`;
- shortcut: `live-overlay --translation-device cpu --offline --no-auto-start`;
- free space: at least 12 GiB;
- system RAM: 8 GiB minimum, 16 GiB recommended;
- Authenticode: unsigned;
- output: ignored `dist\installer-offline-0.2.0`.

## Pinned bundle

The required bundle has 17 files and 4,826,649,490 bytes:

| Component | Fixed identity | License |
|---|---|---|
| Silero VAD | 6.2.1; ONNX SHA-256 `1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3` | MIT |
| GigaAM | `ai-sage/GigaAM-Multilingual`, `large_ctc`, revision `3905cd51c3ed4e88c8edf33f3302969ba480a327`; weight SHA-256 `c3fabefb50b41f08f4d7ad44e02c26c37d242882704cdcca2ebd98e45eff73d1` | MIT |
| NLLB | `facebook/nllb-200-distilled-600M` at `f8d333a098d19b4fd9a8b18f94170487ad3f821d` | CC-BY-NC-4.0 |

Legacy RNNT weights are not present. Bundle validation rejects unapproved files,
links, junctions, reparse points, unsafe paths, wrong refs/sizes/hashes and
totals. Ordinary hard-linked files are rehashed as normal content. Metadata is
path-free and declares `self_contained=true` and `offline_ready=true`.

## Build and delivery

The builder requires a clean commit-matched CPU onedir and signed official Inno
Setup 7.0.2. It defaults to a 2,000,000,000-byte per-asset limit and native Inno
disk spanning with 1,900,000,000-byte slices whenever predicted or measured
output requires it. There is no custom split, self-extracting archive, Git LFS,
or cache/network fallback.

`SHA256SUMS.txt` covers setup and every numbered `.bin`. All parts must be kept
in one directory and setup is published last. Any failure removes same-version
partial output without touching staging or the retained 0.1.0 delivery.

## Validation boundary

The final candidate is validated only on the development machine from an empty
managed-model state: install, model-doctor, real RU/ZH GUI session, same-version
repair, uninstall/model preservation, reinstall and GUI smoke. VMware, Windows
Sandbox, signing and GitHub Release publication are explicitly outside this
stage. Exact final build/install/model-load, memory and latency measurements are
recorded with the ignored build and validation reports.

Before the final provenance rebuild, the code-identical frozen 0.2.0 rehearsal
loaded Large CTC for the first time in 4.853 seconds and recognized the real
8-second Russian WAV in 1.170 seconds (RTF 0.146). A separate full pipeline run
loaded ASR in 3.747 seconds, NLLB in 1.655 seconds and completed at end-to-end
RTF 1.143. Final installation measurements are reported separately because disk
cache and host load affect timing.
