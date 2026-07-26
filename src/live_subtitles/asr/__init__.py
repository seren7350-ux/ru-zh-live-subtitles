"""Speech-recognition interfaces and ONNX implementation."""

from .base import SpeechRecognizer
from .gigaam_onnx import GigaAMOnnxRecognizer

__all__ = ["SpeechRecognizer", "GigaAMOnnxRecognizer"]
