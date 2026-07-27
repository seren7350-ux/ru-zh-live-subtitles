"""Collect only onnx-asr code and its small preprocessing assets, never model weights."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, get_package_paths

# onnx-asr's resolver maps model names to implementations at runtime.
hiddenimports = collect_submodules("onnx_asr")

_, package_directory = get_package_paths("onnx_asr")
preprocessor_data = Path(package_directory) / "preprocessors" / "data"
destination = "onnx_asr/preprocessors/data"

datas = []
# CPU GigaAM preprocessing reads this 20 KiB filter-bank archive via importlib.resources.
datas.append((str(preprocessor_data / "fbanks.npz"), destination))
# The onnx-asr adapter eagerly creates resamplers for supported WAV sample rates.
# These are small signal-processing graphs, not speech/translation model weights.
for graph in preprocessor_data.glob("resample_*_16.onnx"):
    datas.append((str(graph), destination))
