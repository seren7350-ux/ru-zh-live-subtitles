# Windows Sandbox clean-machine validation

## Outcome

**Clean-machine validation kit prepared; Windows Sandbox unavailable.**

This host cannot be used for the requested disposable-environment runs. The
installed edition is Windows 11 Home, while Windows Sandbox requires an eligible
Pro, Enterprise, or Education edition. The Windows Sandbox AppX package is not
present. A read-only optional-feature query reported that elevation would be
required; the task explicitly prohibited elevation, feature enablement, Hyper-V
changes, restart, BIOS changes, and security-policy changes. No such change was
attempted.

Consequently, this report does **not** claim package-only, offline file, CPU live,
CUDA live, microphone-redirection, Defender-in-Sandbox, or three-instance
reproducibility validation. A reduced `PATH` was not used as a substitute for a
clean machine.

## Source and package baseline

- PR #10 was confirmed mergeable with its `test` GitHub Actions check successful,
  marked Ready, and squash-merged without bypassing CI.
- PR #10 merge commit on `main`: `34e7cab275dc6fa6a92d7c71ee9aba56de5ae076`.
- Validation branch: `test/windows-sandbox-clean-machine`.
- Rebuild profile: `RU_ZH_PACKAGE_PROFILE=optimized`, using the reviewed
  `packaging/combined.spec` default `pyz+py` Torch collection mode.
- Successful rebuild time: 106.747 seconds.
- Combined onedir: 3,064,138,625 bytes, 5,463 files, 98 DLLs.
- Torch subtree: 2,782,103,542 bytes; CUDA-named/runtime subtree calculation:
  2,408,120,526 bytes.
- Console SHA-256:
  `863b7b05ef5abcdd1e2e1a98a69cbe56faf921ea820f9b0f277c5857732bf496`.
- GUI SHA-256:
  `026faadff7daec362f0155a27e81fb3117e07d67015fee447eb7142628fabfba`.
- The package contains two EXEs and one shared dependency tree. The extension
  scan found no WAV, MP3, FLAC, PT, PTH, safetensors, or BIN payload.
- The size differs from the PR #10 baseline by only 996 bytes and has the same
  structure; this is normal rebuild metadata variation, not a footprint change.

The first rebuild attempt reached COLLECT but could not replace an incompletely
removed prior output directory (`WinError 5` followed by `WinError 145`). A
read-only process audit found no project Python, PyInstaller, console, or GUI
process. A non-concurrent retry with the same command completed successfully.
The retry emitted eight PyInstaller warning log lines. The main recurring warning
was the known cross-platform Torch ctypes reference to `/usr/lib64/libgomp.so.1`;
Torch deprecation and missing Triton informational messages were also retained.

The package content scan found no current host user path, repository path,
virtual-environment path, or authentication secret. It did record four benign
upstream/example user-path markers by relative file: the Rust wheel build user
`runneradmin` in `hf_xet.pyd`, `_safetensors_rust.pyd`, and `tokenizers.pyd`, and
the literal documentation placeholder `C:\Users\<username>` in Torch
`_appdirs.py`. These are third-party build/source strings, not paths from this
host. They remain explicit manifest warnings rather than being silently hidden.

## Host capability evidence

| Item | Actual result |
|---|---|
| Windows edition | Microsoft Windows 11 Home |
| Version/build | 10.0.26200, Build 26200, 64-bit |
| Firmware virtualization | Enabled |
| VM monitor extensions / SLAT / DEP | All reported Yes by `systeminfo.exe` |
| Virtualization-based security | Not enabled; no change attempted |
| Sandbox optional feature | State unavailable without elevation; no elevation attempted |
| Windows Sandbox AppX | Not found |
| Sandbox launch | Not attempted because the edition/application prerequisites failed |
| Physical memory | 16,783,233,024 bytes (systeminfo: 16,006 MB) |
| Free physical memory at survey | 6,978,760 KiB |
| C: free space at survey | 308,870,168,576 bytes (287.66 GiB) |
| Generated Sandbox memory policy | 8,192 MB for this 16 GB-class host |

Disk capacity is sufficient for the 3.1 GB package, an exact local model staging
copy, and results. Available RAM would make CPU NLLB validation resource-sensitive
inside an 8 GB Sandbox; this is a constraint to record, not a compatibility pass.

## Unchanged environments

Both existing environments passed `pip check`; no package was installed,
upgraded, downgraded, or re-resolved.

| Component | Version/status |
|---|---|
| Development Python | 3.11.9 |
| Packaging Python | 3.11.9 |
| PyInstaller | 6.21.0 |
| Torch | 2.12.1+cu130 |
| Torch CUDA build | 13.0 |
| Host Torch CUDA availability | True; not evidence for Sandbox CUDA |
| Transformers | 5.14.1 |
| ONNX Runtime | 1.28.0 |
| Host ORT providers | AzureExecutionProvider, CPUExecutionProvider |
| onnx-asr | 0.12.0 |
| Hugging Face Hub | 1.24.0 |
| NumPy | 2.4.6 |
| sounddevice | 0.5.5 |

## Exact local model staging boundary

Cache locations and revisions were derived from current application code,
onnx-asr 0.12.0 resolver code, `refs/main`, and the actual cache structure. They
were not guessed.

| Component | Exact local source | Revision | Required files | License |
|---|---|---|---:|---|
| Silero VAD | application LocalAppData cache, version 6.2.1 | 6.2.1 | 3 | MIT |
| GigaAM | `models--istupakov--gigaam-v3-onnx` | `322c3b29492673eb7d0b434bfa9dfb8653e34d02` | 5 | MIT |
| NLLB | `models--facebook--nllb-200-distilled-600M` | `f8d333a098d19b4fd9a8b18f94170487ad3f821d` | 7 | CC-BY-NC-4.0 |

Only the pinned snapshot files are permitted. T5, M2M100, other Hugging Face
models, blobs, stale snapshots, lock files, tokens, credentials, cookies, user
configuration, Git/SSH data, and audio are rejected. The local staging manifest
contains only relative paths, SHA-256 values, sizes, model IDs, exact revisions,
license identifiers, `local_test_only=true`, and
`model_weights_bundled_in_application=false`.

These model assets are not part of the application package, are not committed,
are not uploaded, and may only be mapped read-only into a local Sandbox. NLLB is
still restricted to non-commercial research validation under CC-BY-NC-4.0.

Actual local staging completed in 313.604 seconds. The model manifest covers 17
files (including both pinned `refs/main` files) totaling 3,377,386,298 bytes:
2,329,081 bytes for Silero, 892,410,871 bytes for GigaAM, and 2,482,646,346
bytes for NLLB. Token, bearer-authorization, credential, email, user-path, and
extra-file scans all passed. The originals were read-only sources; no cache file
was downloaded, rewritten, or deleted.

## Validation kit

The committed toolkit is under `packaging/clean_machine/`:

- `prepare_assets.py` validates the Git commit and two EXEs, scans the package,
  creates relative SHA manifests, and stages only the exact approved caches.
- `generate_sandbox_config.py` validates every mapping, creates unique empty
  writable result directories, chooses conservative memory, and generates
  package-only and cache-backed `.wsb` files with networking disabled.
- `package_only_startup.ps1` checks the absence of Python/Git/source/caches,
  package hashes, CLI help/devices, missing-cache behavior, GUI smoke, read-only
  enforcement, no-network evidence, privacy, and process residue.
- `offline_cache_startup.ps1` verifies both manifests, copies exact assets into a
  disposable writable cache, sets both offline flags, runs doctors, selects CUDA
  only from actual frozen runtime evidence, and supports a local fixed WAV file
  pipeline.
- `collect_results.ps1` writes structured, redacted JSON. Caption text, token-like
  strings, emails, and absolute paths are removed.
- `sandbox-template.wsb` is machine-path-free; real generated `.wsb` files remain
  under ignored `data/clean-machine-validation/`.

Package, model-assets, and scripts mappings are read-only. Results are the only
writable host mapping and use a newly created run-specific empty directory. The
repository, virtual environments, user root, full Hugging Face cache, cameras,
and printers are not mapped. Audio input is enabled for a future eligible-host
test; vGPU may be enabled but cannot determine the result classification.

Both machine-specific ignored configurations were generated successfully with
8,192 MB: package-only has three mappings (package/scripts read-only and one
unique empty results directory writable), while offline-cache adds only the
read-only exact model-assets mapping. Both set `Networking=Disable`,
`AudioInput=Enable`, `VideoInput=Disable`, and `PrinterRedirection=Disable`;
neither contains a token marker. They were not launched on this ineligible host.

The copied staging was independently re-hashed after generation: package
5,463/5,463 files and model-assets 17/17 files matched, with zero failures in
142.388 seconds. Both manifests were separately checked for absolute paths,
token patterns, and emails; all three checks were false.

Automated validation completed without network, model loading, microphone use,
or Sandbox launch:

- final complete source suite: 308 passed in 2.34 seconds;
- final coverage suite: 308 passed in 3.33 seconds, 80% total `live_subtitles` coverage;
- final packaging-environment focused suite: 69 passed in 1.14 seconds;
- development and packaging `pip check`: no broken requirements;
- all three PowerShell startup/result scripts: parser accepted with no errors.

CI runs the normal test suite on Windows. It does not launch Sandbox, build the
multi-gigabyte package, download a model, map a microphone, or cache model data.

## Required eligible-host runs (not completed here)

1. Start a fresh package-only Sandbox with networking disabled and no model
   mapping. Confirm no Python, repository, venv, caches, or prior application log;
   run help/devices/overlay and missing-cache tests; verify package read-only,
   privacy, no recursion, safe exit, and no residual process.
2. Destroy it. Start a new cache-backed Sandbox. Verify manifests and offline
   flags, run VAD/ASR/translation doctors, detect actual Torch CUDA, and complete
   the staged WAV ASR/translation pipeline.
3. Re-enumerate Sandbox audio inputs. If microphone redirection exists, select the
   actual 16 kHz mono device and run the short VAD test. Do not assume device 1.
4. Run GPU live captions only when `torch.cuda.is_available()` is true inside the
   frozen Sandbox. Otherwise run the CPU fallback without GPU latency gates. If
   microphone redirection is unavailable, record that fact and use the mandatory
   file pipeline; do not change host policy or install a virtual device.
5. Destroy the second instance. Start a third new cache-backed instance and repeat
   manifest checks, doctors, overlay, one file pipeline, GUI start/exit, and
   residual-process checks to prove reproducibility.
6. If Defender CLI is available inside Sandbox, scan the read-only package without
   changing exclusions or policy. Otherwise record it as unavailable.

The current host produced no first/second/third Sandbox result, no Sandbox
console/device/doctor output, no actual Sandbox CUDA or translation device, no
microphone-redirection result, no Sandbox file/live captions, no GUI/heartbeat/
queue/RTF/latency metrics, no Sandbox privacy scan, and no Sandbox Defender scan.
Those fields remain explicitly **not run**, not passed.

## Recommendation gate

The next validation should be on an eligible Pro/Enterprise/Education Windows
machine—preferably also an independent physical GPU machine—using this kit. Do
not begin an installer or make portability/production claims until the clean
package-only and offline-cache runs are reproducible. Translation runtime
migration remains a separate evaluation and should not be started merely to work
around this host-edition limitation.
