"""Minimal NumPy/ONNX Runtime wrapper for the pinned Silero streaming model."""

from __future__ import annotations

import importlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .vad_assets import VadAssetError, validate_vad_assets

SAMPLE_RATE = 16_000
CHUNK_SAMPLES = 512
CONTEXT_SAMPLES = 64
STATE_SHAPE = (2, 1, 128)


class VadInferenceError(RuntimeError):
    """Raised for invalid VAD inputs, runtime metadata, or model outputs."""


@dataclass(frozen=True)
class OnnxValueMetadata:
    name: str
    shape: tuple[Any, ...]
    type: str


class SileroOnnxVad:
    """Run the official Silero VAD 6.2.1 ONNX model with explicit stream state."""

    def __init__(
        self,
        model_path: Path | None = None,
        *,
        provider: str = "CPUExecutionProvider",
        session_factory: Callable[[Path, str], Any] | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._requested_model_path = model_path
        self.provider = provider
        self._session_factory = session_factory
        self._clock = clock
        self._session: Any | None = None
        self.model_path: Path | None = None
        self.inputs: tuple[OnnxValueMetadata, ...] = ()
        self.outputs: tuple[OnnxValueMetadata, ...] = ()
        self.load_seconds = 0.0
        self.session_creation_count = 0
        self._state = np.zeros(STATE_SHAPE, dtype=np.float32)
        self._context = np.zeros((1, CONTEXT_SAMPLES), dtype=np.float32)

    @staticmethod
    def _metadata(values: list[Any]) -> tuple[OnnxValueMetadata, ...]:
        return tuple(
            OnnxValueMetadata(value.name, tuple(value.shape), str(value.type))
            for value in values
        )

    def _create_session(self, path: Path) -> Any:
        if self._session_factory is not None:
            return self._session_factory(path, self.provider)
        try:
            ort = importlib.import_module("onnxruntime")
        except Exception as exc:
            raise VadInferenceError(f"ONNX Runtime is unavailable: {exc}") from exc
        available = list(ort.get_available_providers())
        if self.provider not in available:
            choices = ", ".join(available) or "none"
            raise VadInferenceError(
                f"VAD provider {self.provider!r} is unavailable. Available providers: {choices}."
            )
        options = ort.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        try:
            return ort.InferenceSession(
                str(path), sess_options=options, providers=[self.provider]
            )
        except Exception as exc:
            raise VadInferenceError(f"Unable to load Silero ONNX model at {path}: {exc}") from exc

    def prepare(self) -> None:
        """Create one CPU inference session and record its actual metadata."""

        if self._session is not None:
            return
        if self._requested_model_path is None:
            try:
                path = validate_vad_assets().model_path
            except VadAssetError as exc:
                raise VadInferenceError(str(exc)) from exc
        else:
            path = self._requested_model_path.expanduser().resolve()
            if not path.is_file():
                raise VadInferenceError(f"Silero ONNX model does not exist: {path}")

        started = self._clock()
        session = self._create_session(path)
        inputs = self._metadata(list(session.get_inputs()))
        outputs = self._metadata(list(session.get_outputs()))
        input_names = {value.name for value in inputs}
        output_names = {value.name for value in outputs}
        if input_names != {"input", "state", "sr"}:
            raise VadInferenceError(f"Unexpected Silero ONNX inputs: {sorted(input_names)}")
        if output_names != {"output", "stateN"}:
            raise VadInferenceError(f"Unexpected Silero ONNX outputs: {sorted(output_names)}")
        self.load_seconds = self._clock() - started
        self.model_path = path
        self.inputs = inputs
        self.outputs = outputs
        self._session = session
        self.session_creation_count += 1
        self.reset()

    def reset(self) -> None:
        """Reset recurrent state and 16 kHz context without recreating the session."""

        self._state = np.zeros(STATE_SHAPE, dtype=np.float32)
        self._context = np.zeros((1, CONTEXT_SAMPLES), dtype=np.float32)

    @staticmethod
    def _validate_chunk(chunk: np.ndarray) -> np.ndarray:
        if not isinstance(chunk, np.ndarray):
            raise VadInferenceError("VAD chunk must be a NumPy array.")
        if chunk.dtype != np.float32:
            raise VadInferenceError("VAD chunk dtype must be float32.")
        if chunk.ndim != 1:
            raise VadInferenceError("VAD chunk must be one-dimensional.")
        if chunk.shape[0] != CHUNK_SAMPLES:
            raise VadInferenceError(
                f"VAD chunk must contain exactly {CHUNK_SAMPLES} samples."
            )
        if not np.isfinite(chunk).all():
            raise VadInferenceError("VAD chunk contains NaN or infinite values.")
        if float(np.max(np.abs(chunk), initial=0.0)) > 1.0:
            raise VadInferenceError("VAD chunk values must stay within [-1, 1].")
        return chunk

    def speech_probability(self, chunk: np.ndarray) -> float:
        """Return one probability while carrying state/context into the next chunk."""

        samples = self._validate_chunk(chunk)
        self.prepare()
        assert self._session is not None
        model_input = np.concatenate((self._context, samples.reshape(1, -1)), axis=1)
        try:
            output, state = self._session.run(
                ["output", "stateN"],
                {
                    "input": model_input,
                    "state": self._state,
                    "sr": np.asarray(SAMPLE_RATE, dtype=np.int64),
                },
            )
        except Exception as exc:
            raise VadInferenceError(f"Silero ONNX inference failed: {exc}") from exc
        probability = float(np.asarray(output).reshape(-1)[0])
        next_state = np.asarray(state, dtype=np.float32)
        if not np.isfinite(probability) or not 0.0 <= probability <= 1.0:
            raise VadInferenceError(
                f"Silero ONNX returned an invalid speech probability: {probability!r}."
            )
        if next_state.shape != STATE_SHAPE or not np.isfinite(next_state).all():
            raise VadInferenceError(
                f"Silero ONNX returned invalid recurrent state shape {next_state.shape}."
            )
        self._state = next_state.copy()
        self._context = model_input[:, -CONTEXT_SAMPLES:].copy()
        return probability
