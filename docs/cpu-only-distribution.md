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

Model weights, Hugging Face caches, VAD assets, recordings, logs, staging,
virtual environments, and Git metadata are outside the application package.
The installer performs no download and starts the GUI in offline, no-auto-start
mode. See [model assets setup](model-assets-setup.md).

This candidate is unsigned and has only been validated on the development
machine. It has not been validated on a clean Windows machine and is not a
public Release, production-ready distribution, or commercial-use approval.
