# Self-contained CPU offline installer

This unsigned per-user installer is the published non-commercial course delivery. It combines
the provenance-bound CPU onedir and every pinned model asset needed for offline
Russian speech recognition and Chinese translation. Publication is not
production certification, commercial-use approval, or a clean-machine result
for this installer revision.

## Delivery contract

- application: `%LOCALAPPDATA%\Programs\RuZhLiveSubtitles`;
- models: `%LOCALAPPDATA%\ru-zh-live-subtitles\models`;
- privileges: current user, no UAC or administrator access;
- prerequisites: no Python, source checkout, token, pre-existing cache, or
  manual model copy;
- network: no download during setup or first run;
- shortcut: `live-overlay --translation-device cpu --offline --no-auto-start`;
- minimum free space before setup: 8 GiB;
- Authenticode: intentionally unsigned.

The complete delivery directory is `dist\installer-offline`. A preflight using
maximum LZMA2 compression produced one 1,762,415,746-byte setup (1.641 GiB), so
the expected teacher delivery is a single file of approximately 1.8 GB. Exact
final file size and SHA-256 are recorded in ignored `build-report.json`. The
builder still enforces the general rule: at 3.8 GB or larger it rebuilds with
native Inno disk spanning, in which case the whole directory must be copied.
The old approximately 216 MB model-less setup under `dist\installer` is
historical and cannot be delivered alone.

## Pinned model bundle

The existing verified staging is supplied explicitly through
`-ModelAssetsRoot`; the builder never discovers the user's Hugging Face cache.
The validated payload has 17 model files and 3,377,386,294 bytes:

| Component | Fixed identity | License |
|---|---|---|
| Silero VAD | 6.2.1; ONNX SHA-256 `1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3` | MIT |
| GigaAM ONNX | `istupakov/gigaam-v3-onnx` at `322c3b29492673eb7d0b434bfa9dfb8653e34d02` | MIT |
| NLLB | `facebook/nllb-200-distilled-600M` at `f8d333a098d19b4fd9a8b18f94170487ad3f821d` | CC-BY-NC-4.0, non-commercial only |

`packaging/model_bundle.py` parses `model-manifest.json`, requires exactly the
pinned model/file set, checks safe relative paths, strict 40-byte lowercase
revision refs with no BOM/CR/LF, known sizes, every manifest SHA-256, and the
fixed Silero model SHA. Extra files, links, path traversal, missing assets,
wrong identity, size, hash, or total are rejected before ISCC. The generated
`MODEL_BUNDLE_METADATA.json` contains no staging path, username, host, token,
remote, or credential.

## Build

From a clean tracked worktree whose CPU onedir was built from the same commit:

```powershell
.\packaging\installer\build_installer.ps1 `
  -ExpectedCommit (git rev-parse HEAD) `
  -CpuDist .\dist\ru-zh-subtitles-cpu `
  -ModelAssetsRoot <verified-model-assets> `
  -OutputDir .\dist\installer-offline `
  -IsccPath "$env:LOCALAPPDATA\Programs\Inno Setup 7\ISCC.exe"
```

The transaction verifies Git state, CPU provenance/policy, frozen CPU doctor,
the entire model bundle, official Inno 7.0.2 signature/version, release
metadata, compiler result, output hashes, warnings, and Authenticode state.
Metadata/log/report/instructions and any `.bin` slices publish before setup;
setup is the final success marker. Failure removes all same-version offline
outputs and leaves model staging untouched.

## Install, verify, repair and uninstall

For development-machine empty-state validation, use a new temporary
`LOCALAPPDATA`, remove Python/venv entries from that process's `PATH`, clear
explicit `HF_HOME` and `HF_HUB_CACHE`, and confirm the temporary model root does
not exist. Do not delete the real user cache.

After silent or interactive current-user install, run:

```powershell
& "$env:LOCALAPPDATA\Programs\RuZhLiveSubtitles\ru-zh-subtitles-console.exe" model-doctor
```

Success is exit code 0 with Silero, GigaAM and NLLB OK and `Offline readiness:
READY`. Launch the same command represented by the shortcut, select a real
microphone, Start, speak Russian, confirm RU/ZH captions, Stop, and verify the
microphone, workers, temporary WAVs and processes are released. Application
diagnostics must show no download, and application-owned TCP connections must
remain zero.

Running the same installer again is the repair path. The stable AppId must leave
one uninstall entry and preserve key model hashes. Uninstall removes the app,
shortcuts and uninstall entry but intentionally keeps the model root. A later
reinstall reuses the same layout without nesting or duplication. To reclaim
approximately 3.4 GB after uninstall, manually delete:

```text
%LOCALAPPDATA%\ru-zh-live-subtitles\models
```

Defender scans must leave real-time protection enabled, add no exclusion, and
cover the CPU dist, delivery files, installed app and installed model root.
