# CPU-only distribution policy for 0.3.0

The sole new course-delivery candidate is a Windows x64 CPU-only onedir built by
`packaging/combined_cpu.spec`. It contains both launchers and application
runtime code but zero product model weights. A separately verified external
bundle adds exactly 17 files and 4,826,649,490 bytes of Silero VAD 6.2.1,
official GigaAM Multilingual Large CTC and NLLB assets to the installer.

The formal Python 3.11.9 environment pins Torch 2.10.0+cpu, TorchAudio
2.10.0+cpu, Transformers 5.14.1, Hydra Core 1.3.2, OmegaConf 2.3.0 and
SoundFile 0.13.1. Torch and TorchAudio come from the official PyTorch CPU index.
Policy requires `torch.version.cuda is None`,
`torch.cuda.is_available() is False`, zero CUDA DLL/files/bytes, zero product
model weight files/bytes, `torch_cpu.dll`, and both top-level executables.

The spec rejects a dirty worktree, writes path-safe `CPU_BUILD_METADATA.json`,
and copies it with README, notices and model documents to the onedir root. The
metadata binds application version 0.3.0 and runtime family `cpu` to the clean
lowercase Git commit and `packaging/combined_cpu.spec`. Validators cross-check
that commit/version before the installer runs Inno Setup.

PyInstaller explicitly collects TorchAudio, Transformers dynamic-module
support, Hydra/OmegaConf, YAML and SoundFile so the frozen executable can load
the verified external `modeling_gigaam.py` with `trust_remote_code=True` and
`local_files_only=True`. The snapshot remains external. The backend does not
silently fall back to legacy RNNT if dynamic loading fails.

The retained GPU spec is not a 0.3.0 build input. Generated onedirs, models,
recordings, logs and manifests remain ignored. The 0.1.0 RNNT installer/tag and
its evidence remain unchanged.

The historical 0.2.0 frozen rehearsal on 2026-07-31 measured 613,257,398 bytes
across 5,616 files.
From a repository-external Unicode-and-space directory, first Large CTC load
took 4.853 seconds and real 8-second recognition took 1.170 seconds (RTF 0.146).
The full offline ASR→NLLB process measured ASR load 3.747 seconds, NLLB load
1.655 seconds and end-to-end RTF 1.143. These development-machine values are a
frozen CPU baseline, not a guarantee for another Windows computer.
