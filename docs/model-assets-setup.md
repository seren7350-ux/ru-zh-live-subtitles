# Model assets setup

The self-contained CPU offline installer includes all three pinned asset sets
and never downloads them. Setup installs those assets automatically outside the
application directory. Manual preparation is needed only for development runs
or the historical model-less installer, not for the teacher delivery.

The application-managed root is:

```text
%LOCALAPPDATA%\ru-zh-live-subtitles\models
```

The effective Hugging Face cache is selected in this order: an explicit
`HF_HUB_CACHE`, an explicit `HF_HOME`, the application-managed
`models\hf-home\hub`, then the normal user Hugging Face cache. Explicit user
settings are never overwritten and no permanent environment variable is set.

## Pinned assets

| Component | Model and revision | Required location |
|---|---|---|
| VAD | Silero VAD `6.2.1` | `models\silero-vad\6.2.1` |
| ASR | `istupakov/gigaam-v3-onnx` at `322c3b29492673eb7d0b434bfa9dfb8653e34d02` | selected Hub cache |
| Translation | `facebook/nllb-200-distilled-600M` at `f8d333a098d19b4fd9a8b18f94170487ad3f821d` | selected Hub cache |

NLLB-200 distilled 600M is licensed CC-BY-NC-4.0 and is restricted to
non-commercial use. This project remains a local research/non-commercial
candidate; these instructions do not approve commercial use or redistribution.

## Installer-managed layout

The build accepts only an explicit, fully verified `model-assets` staging root.
The installer copies its contents to the managed root. It never consults the
builder's normal Hugging Face cache and never places models in `{app}`. The
installed structure is:

```text
models\
  hf-home\
    hub\
      models--istupakov--gigaam-v3-onnx\
        refs\main
        snapshots\322c3b29492673eb7d0b434bfa9dfb8653e34d02\...
      models--facebook--nllb-200-distilled-600M\
        refs\main
        snapshots\f8d333a098d19b4fd9a8b18f94170487ad3f821d\...
  silero-vad\
    6.2.1\
      silero_vad.onnx
      LICENSE
      metadata.json
```

Each `refs\main` must be exactly the pinned 40-byte lowercase hexadecimal
revision with no BOM, CR, LF, or trailing whitespace.

## Verify after installation

From the installed application directory run:

```powershell
.\ru-zh-subtitles-console.exe model-doctor
```

Exit code 0 and `Offline readiness: READY` mean every path, revision, required
file, and known file size passed the fast check. Exit code 2 reports the exact
missing or invalid assets without importing Torch, Transformers, ONNX Runtime,
or model code. A successful self-contained install is expected to be READY
without copying files or setting `HF_HOME`.

Installed shortcuts start with `--offline`. The process sets only its own
`HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`; missing assets block Start and
are never downloaded. Uninstall removes the application and its shortcuts but
preserves this model root and normal Hugging Face caches. Delete external model
assets manually only when you intend to reclaim approximately 3.4 GB.
