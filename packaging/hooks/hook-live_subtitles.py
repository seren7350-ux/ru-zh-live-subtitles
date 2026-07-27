"""PyInstaller analysis additions for modules imported through runtime factories."""

from PyInstaller.utils.hooks import copy_metadata

# ASR and VAD wrappers load ONNX Runtime through importlib.
hiddenimports = ["onnxruntime"]
# The GigaAM wrapper delays onnx-asr import until the first model preparation.
hiddenimports += ["onnx_asr"]
# Translation runtime delays PyTorch import until translation model preparation.
hiddenimports += ["torch"]
# Translation engines delay Transformers import until a translator is selected.
hiddenimports += ["transformers"]

datas = []
# Runtime version reporting and dependency checks use installed package metadata.
for distribution in (
    "ru-zh-live-subtitles",
    "onnx-asr",
    "onnxruntime",
    "numpy",
    "sounddevice",
    "torch",
    "transformers",
    "tokenizers",
    "sentencepiece",
    "safetensors",
    "huggingface-hub",
):
    datas += copy_metadata(distribution)
