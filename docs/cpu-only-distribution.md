# CPU-only distribution policy

The sole end-user distribution candidate is the Windows x64 CPU-only onedir and
its per-user installer. `packaging/combined_cpu.spec` is the only source for
that candidate. The installed CPU application is approximately 658 MB; separate
local model assets of approximately 3.4 GB are required before transcription
and translation can run.

The GPU spec and supporting hook/profile remain in the repository only for
internal development, historical benchmarks, and possible future experiments.
They are not distributed, are not supported as an end-user package, and no GPU
installer is produced.

Before installer compilation, the CPU policy requires the two application
executables, `torch_cpu.dll`, `torch.version.cuda is None`,
`torch.cuda.is_available() is False`, zero CUDA DLLs, and zero model weights.
The current application version continues to come only from
`live_subtitles.__version__`.

The spec first rejects a dirty Git worktree, then writes a path-safe
`CPU_BUILD_METADATA.json` under ignored `build/cpu-provenance`. After COLLECT,
it publishes that file at the CPU onedir root beside `README.md`,
`THIRD_PARTY_NOTICES.md`, and `MODEL_SETUP.txt`. The metadata binds the onedir
to the clean lowercase Git HEAD, version `0.1.0`, CPU runtime family, Windows
x64 platform, and `packaging/combined_cpu.spec`. The GPU spec is unchanged and
does not collect CPU provenance.

`validate_cpu_distribution.py`, `release_metadata.py`, and the installer build
all cross-check the embedded version and commit against the current clean HEAD
and explicit expected commit. A stale or missing provenance file is rejected
before frozen doctor or ISCC compilation. The full release manifest includes
the provenance file and the three root documents.

Model weights, Hugging Face caches, VAD assets, recordings, logs, staging,
virtual environments, and Git metadata are outside the application package.
The installer performs no download and starts the GUI in offline, no-auto-start
mode. See [model assets setup](model-assets-setup.md).

This candidate is unsigned and has only been validated on the development
machine. It has not been validated on a clean Windows machine and is not a
public Release, production-ready distribution, or commercial-use approval.
