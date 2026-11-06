# Single-file Windows CPU distribution

> Archived experiment: cancelled on 2026-11-07 before a final EXE was produced.
> This prototype is retained for reference, is not a supported release, and has
> not passed clean-machine acceptance. Use `packaging/installer` for the verified
> setup EXE plus numbered data volumes. The description below documents the
> intended prototype behavior, not a delivered product.

The deliverable is `RuZhSubtitles.exe`. Copy only that file to a writable local disk and double-click it. The supported target is 64-bit Windows 10/11 with the inbox .NET Framework 4.x and the inbox bsdtar with XZ support. Python, pip, PyTorch, 7-Zip and separate model downloads are not required on the target. The CPU must support the packaged runtime. The model licenses are included with the extracted application.

First launch unpacks the runtime and all three model sets under the current user's local application data. Allow space for the EXE and the unpacked runtime/models (about 5.43 GB unpacked). Each launch checks the embedded file inventory. A valid installation is reused; missing or changed payload files cause a fresh verified extraction. A partially prepared copy cannot become active. User transcripts are written by the app to its normal user subtitle directory. Press F8 to start or stop.

For unattended verification, run `RuZhSubtitles.exe --verify-only` and wait for the process. Exit code zero means the full runtime and models were verified on disk without opening the microphone.

To build from the repository, use Python 3.11+, a 7-Zip compatible CLI supporting XZ on stdin/stdout, and the Windows .NET Framework x64 C# compiler:

    python packaging/single_file/build.py <cpu-onedir> <validated-model-directory> <build-work> <new-output.exe>

The output must be a new path. Packaging compresses a tar stream and appends it to a small Windows launcher, so the extracted model files can individually exceed 2 GB. The launcher checks SHA-256 digests before starting the offline CPU app.
