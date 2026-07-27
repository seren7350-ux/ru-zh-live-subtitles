# Third-party notices for the Windows packaging spike

This inventory records only information verified from the installed package
metadata, files shipped with the installed runtime, cached model metadata, or
the linked upstream source. It is not a substitute for a complete legal review.
The onedir build is unsigned and is intended for learning, research, and
non-commercial feasibility validation.

## Components included in the onedir application

| Component | Evaluated version | Verified license | Verification source |
|---|---:|---|---|
| Python | 3.11.9 | Python Software Foundation License Version 2 and the additional licenses listed by CPython | Installed `LICENSE.txt`; [Python license documentation](https://docs.python.org/3.11/license.html) |
| Tk/Tcl | 8.6 | Tcl/Tk license terms | Installed `tcl/tk8.6/license.terms`; [Tcl/Tk license page](https://www.tcl-lang.org/software/tcltk/license.html) |
| PyInstaller | 6.21.0 | GPL-2.0-or-later with the PyInstaller special exception | Installed distribution metadata and `COPYING.txt`; [PyInstaller license](https://pyinstaller.org/en/stable/license.html) |
| NumPy | 2.4.6 | BSD-3-Clause plus separately identified bundled-component licenses | Installed `License-Expression` and distribution `licenses/` directory |
| ONNX Runtime | 1.28.0 | MIT | Installed distribution metadata and `LICENSE` |
| onnx-asr | 0.12.0 | MIT | Installed distribution metadata and `LICENSE` |
| sounddevice | 0.5.5 | MIT | Installed distribution metadata; license header in `sounddevice.py` |
| PortAudio | wheel-bundled binary | MIT; the collected default Windows binary excludes the optional ASIO DLL | `_sounddevice_data/portaudio-binaries/README.md`; [PortAudio license](https://www.portaudio.com/license.html) |
| PyTorch | 2.12.1+cu130 | BSD-3-Clause; bundled third-party components have their own notices | Installed distribution metadata, `LICENSE`, and `NOTICE` |
| Transformers | 5.14.1 | Apache-2.0 | Installed distribution metadata and `LICENSE` |
| Hugging Face Hub | 1.24.0 | Apache-2.0 | Installed distribution metadata and `LICENSE` |
| tokenizers | 0.22.2 | Apache-2.0 | Installed distribution classifier and license file |
| SentencePiece | 0.2.2 | Apache-2.0 | Installed `License-Expression` and license files |
| safetensors | 0.8.0 | Apache-2.0 | Installed distribution classifier and license file |
| CFFI | 2.1.0 | MIT-0 | Installed `License-Expression` and license file |

The build preserves installed distribution metadata and relevant upstream
notices where PyInstaller hooks collect them. Python and Tk license files are
also explicitly copied into the onedir `licenses/` directory. A complete file
and binary review is still required before public distribution.

## External model assets that are not bundled

No model weights, Hugging Face snapshots, user cache, real WAV files, or tokens
are included in `dist`.

| External asset | Evaluated source | Verified license/boundary |
|---|---|---|
| Silero VAD 6.2.1 ONNX | Pinned official wheel asset prepared into the user's LocalAppData cache | MIT, verified from the cached wheel `LICENSE` and [upstream license](https://github.com/snakers4/silero-vad/blob/master/LICENSE) |
| GigaAM-v3 E2E RNN-T ONNX | `istupakov/gigaam-v3-onnx`, derived from the GigaAM project | MIT, stated by the [ONNX model card](https://huggingface.co/istupakov/gigaam-v3-onnx) and [upstream GigaAM license](https://github.com/salute-developers/GigaAM/blob/main/LICENSE) |
| NLLB-200 distilled 600M | `facebook/nllb-200-distilled-600M` | CC-BY-NC-4.0; non-commercial research model. See the [official model card](https://huggingface.co/facebook/nllb-200-distilled-600M). |

NLLB is a non-commercial candidate. The package does not include its weights;
the user must prepare an external model cache. No statement here approves
commercial distribution. A full license, attribution, export-control, privacy,
and dependency audit remains required before any distribution beyond this
feasibility evaluation.
