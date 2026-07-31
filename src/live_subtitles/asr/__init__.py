"""Backend-neutral ASR contract and the current GigaAM RNNT backend."""

from .base import (
    AsrError,
    AudioTranscriptionError,
    InvalidAudioFileError,
    ModelLoadError,
    ProviderUnavailableError,
    RecognitionMetrics,
    SpeechRecognizer,
)
from .gigaam_onnx import GigaAMOnnxRecognizer

__all__ = [
    "AsrError",
    "AudioTranscriptionError",
    "GigaAMOnnxRecognizer",
    "InvalidAudioFileError",
    "ModelLoadError",
    "ProviderUnavailableError",
    "RecognitionMetrics",
    "SpeechRecognizer",
]
