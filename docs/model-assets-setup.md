# Model assets setup

The current source migration requires three pinned asset sets and never downloads
ASR weights at runtime. The existing teacher installer still contains the former
RNNT/ONNX asset and has not been rebuilt for Large CTC; use this document's new
identity only for source validation and the next packaging stage.

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
| ASR | `ai-sage/GigaAM-Multilingual`, variant `large_ctc`, at `3905cd51c3ed4e88c8edf33f3302969ba480a327` | selected Hub cache or explicit development snapshot |
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
      models--ai-sage--GigaAM-Multilingual\
        refs\main
        snapshots\3905cd51c3ed4e88c8edf33f3302969ba480a327\...
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
assets manually only when you intend to reclaim disk space. The next installer
build must recalculate the total because the Large CTC snapshot alone is
2,341,674,025 bytes.

For development only, point the backend at the exact canonical snapshot without
changing global environment settings:

```powershell
$env:LIVE_SUBTITLES_GIGAAM_MULTILINGUAL_SNAPSHOT = "<staging>\3905cd51c3ed4e88c8edf33f3302969ba480a327"
python -m live_subtitles model-doctor
Remove-Item Env:LIVE_SUBTITLES_GIGAAM_MULTILINGUAL_SNAPSHOT
```

The snapshot must contain the official `.gitattributes`, `README.md`,
`config.json`, `modeling_gigaam.py`, and `pytorch_model.bin` files. Its license
is MIT. Model weights, remote-code snapshots, manifests containing host paths,
and caches remain ignored and must not be committed or uploaded.
