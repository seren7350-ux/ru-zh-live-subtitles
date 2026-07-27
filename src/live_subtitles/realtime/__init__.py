"""Direct ONNX VAD building blocks for files and live microphone capture."""

from .live_vad import LiveVadError, LiveVadResult, LiveVadSession
from .metrics import AudioBlock, LiveVadMetrics, SegmentMetrics, TimingAccumulator
from .microphone import MicrophoneCapture, MicrophoneCaptureError
from .segmenter import AudioSegment, VadSegmenter
from .vad_assets import VadAssetError, VadAssetInfo, prepare_vad_assets
from .vad_model import SileroOnnxVad, VadInferenceError

__all__ = [
    "AudioSegment",
    "AudioBlock",
    "LiveVadError",
    "LiveVadMetrics",
    "LiveVadResult",
    "LiveVadSession",
    "MicrophoneCapture",
    "MicrophoneCaptureError",
    "SegmentMetrics",
    "TimingAccumulator",
    "SileroOnnxVad",
    "VadAssetError",
    "VadAssetInfo",
    "VadInferenceError",
    "VadSegmenter",
    "prepare_vad_assets",
]
"""Real-time microphone and VAD components for terminal prototypes."""

from .live_subtitles import LiveTerminalResult, LiveTerminalSession

__all__ = ["LiveTerminalResult", "LiveTerminalSession"]
