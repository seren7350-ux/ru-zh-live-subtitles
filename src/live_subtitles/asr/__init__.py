"""Backend-neutral ASR contract and explicit GigaAM implementations."""

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
from .gigaam_multilingual_ctc import GigaAMMultilingualCtcRecognizer
from .factory import create_recognizer

__all__ = [
    "AsrError",
    "AudioTranscriptionError",
    "GigaAMOnnxRecognizer",
    "GigaAMMultilingualCtcRecognizer",
    "InvalidAudioFileError",
    "ModelLoadError",
    "ProviderUnavailableError",
    "RecognitionMetrics",
    "SpeechRecognizer",
    "create_recognizer",
]
