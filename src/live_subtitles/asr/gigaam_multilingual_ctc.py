"""Offline adapter for the pinned official GigaAM Multilingual Large CTC model."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import time
import warnings
import wave
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator
from unittest.mock import patch

import numpy as np

from ..config import DEFAULT_ASR_MODEL, DEFAULT_PROVIDER
from ..model_assets import (
    GIGAAM_MULTILINGUAL_MODEL_ID,
    GIGAAM_MULTILINGUAL_REVISION,
    GIGAAM_MULTILINGUAL_VARIANT,
    MODEL_SPECS,
    ModelAssetError,
    ModelAssetSpec,
    resolve_model_snapshot,
)
from .base import (
    AudioTranscriptionError,
    InvalidAudioFileError,
    ModelLoadError,
    ProviderUnavailableError,
    RecognitionMetrics,
)

SAMPLE_RATE = 16_000
MAX_SHORT_AUDIO_SECONDS = 25.0
OFFICIAL_MODELING_SHA256 = (
    "6d02e640fbb5738ab11c030520a68654ef32f4ff363723db10534cf8b5d5c0e7"
)


@dataclass(frozen=True)
class _Runtime:
    torch: Any
    torchaudio: Any
    transformers: Any
    dynamic_module_utils: Any


@dataclass(frozen=True)
class _WaveAudio:
    samples: np.ndarray
    sample_rate: int
    duration_seconds: float


def _official_spec() -> ModelAssetSpec:
    return next(
        spec
        for spec in MODEL_SPECS
        if spec.key == "gigaam-multilingual-large-ctc"
    )


def _import_runtime() -> _Runtime:
    try:
        torch = importlib.import_module("torch")
        torchaudio = importlib.import_module("torchaudio")
        transformers = importlib.import_module("transformers")
        dynamic_module_utils = importlib.import_module(
            "transformers.dynamic_module_utils"
        )
    except Exception as exc:
        raise ModelLoadError(
            "The GigaAM Multilingual runtime is unavailable. Install the "
            "'asr-multilingual' dependency group with matching Torch and TorchAudio "
            f"builds. Original error: {exc}"
        ) from exc
    return _Runtime(torch, torchaudio, transformers, dynamic_module_utils)


def _base_version(value: object) -> str:
    return str(value).split("+", 1)[0]


def _validate_runtime(runtime: _Runtime) -> None:
    torch_version = _base_version(getattr(runtime.torch, "__version__", ""))
    torchaudio_version = _base_version(getattr(runtime.torchaudio, "__version__", ""))
    transformers_version = _base_version(
        getattr(runtime.transformers, "__version__", "")
    )
    if torch_version and not torch_version.startswith("2.10."):
        raise ModelLoadError(
            f"Official Large CTC runtime requires Torch 2.10.x; found {torch_version}."
        )
    if torchaudio_version and not torchaudio_version.startswith("2.10."):
        raise ModelLoadError(
            "Official Large CTC runtime requires TorchAudio 2.10.x; "
            f"found {torchaudio_version}."
        )
    if transformers_version and not transformers_version.startswith("5."):
        raise ModelLoadError(
            "Official Large CTC runtime requires Transformers 5.x; "
            f"found {transformers_version}."
        )
def _normalize_provider(value: str) -> str:
    aliases = {
        "cpu": "cpu",
        "cpuexecutionprovider": "cpu",
    }
    normalized = aliases.get(value.casefold())
    if normalized is None:
        raise ProviderUnavailableError(
            f"Unsupported GigaAM provider {value!r}; this backend supports only 'cpu'."
        )
    return normalized


def _validate_snapshot(snapshot: Path) -> Path:
    spec = _official_spec()
    resolved = snapshot.expanduser().resolve()
    if not resolved.is_dir():
        raise ModelLoadError("The pinned GigaAM Multilingual snapshot directory is missing.")
    expected_sizes = dict(spec.expected_sizes)
    problems: list[str] = []
    for relative in spec.required_files:
        path = resolved / relative
        if not path.is_file():
            problems.append(f"missing {relative}")
            continue
        expected = expected_sizes.get(relative)
        if expected is not None and path.stat().st_size != expected:
            problems.append(
                f"{relative} has {path.stat().st_size} bytes; expected {expected}"
            )
    if problems:
        raise ModelLoadError(
            "The pinned GigaAM Multilingual snapshot is incomplete: "
            + "; ".join(problems)
        )
    modeling = resolved / "modeling_gigaam.py"
    digest = hashlib.sha256(modeling.read_bytes()).hexdigest()
    if digest != OFFICIAL_MODELING_SHA256:
        raise ModelLoadError("The pinned official modeling_gigaam.py SHA-256 is invalid.")
    try:
        config = json.loads((resolved / "config.json").read_text(encoding="utf-8"))
        inner = config["cfg"]["model"]["cfg"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ModelLoadError(f"The pinned GigaAM config cannot be validated: {exc}") from exc
    identity = (
        inner.get("model_name"),
        inner.get("model_class"),
        inner.get("sample_rate"),
    )
    if identity != ("multilingual_large_ctc", "ctc", SAMPLE_RATE):
        raise ModelLoadError(
            "The pinned snapshot is not the required multilingual_large_ctc 16 kHz model."
        )
    vocabulary = inner.get("decoding", {}).get("vocabulary")
    if not isinstance(vocabulary, list) or len(vocabulary) != 70:
        raise ModelLoadError("The pinned Large CTC vocabulary must contain 70 tokens.")
    return resolved


@contextmanager
def _official_remote_code_imports(runtime: _Runtime) -> Iterator[None]:
    """Ignore one verified TYPE_CHECKING-only optional import in Transformers 5."""

    original = runtime.dynamic_module_utils.get_imports

    def get_imports(filename: str | os.PathLike[str]) -> list[str]:
        imports = list(original(filename))
        path = Path(filename)
        if path.name != "modeling_gigaam.py":
            return imports
        if hashlib.sha256(path.read_bytes()).hexdigest() != OFFICIAL_MODELING_SHA256:
            raise ModelLoadError("Unexpected modeling_gigaam.py content during remote-code load.")
        return [name for name in imports if name != "pyannote"]

    with patch.object(runtime.dynamic_module_utils, "get_imports", get_imports):
        yield


def _read_pcm_wav(path: Path) -> _WaveAudio:
    try:
        with wave.open(str(path), "rb") as wav_file:
            channels = wav_file.getnchannels()
            width = wav_file.getsampwidth()
            sample_rate = wav_file.getframerate()
            frame_count = wav_file.getnframes()
            compression = wav_file.getcomptype()
            payload = wav_file.readframes(frame_count)
    except (OSError, EOFError, wave.Error) as exc:
        raise InvalidAudioFileError(f"Unable to read WAV audio {path.name!r}: {exc}") from exc
    if channels <= 0 or sample_rate <= 0:
        raise InvalidAudioFileError("WAV channels and sample rate must be greater than zero.")
    if compression != "NONE" or width not in {1, 2, 3, 4}:
        raise InvalidAudioFileError(
            "Only uncompressed PCM WAV with 8-, 16-, 24-, or 32-bit samples is supported."
        )
    try:
        if width == 1:
            samples = (np.frombuffer(payload, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
        elif width == 2:
            samples = np.frombuffer(payload, dtype="<i2").astype(np.float32) / 32768.0
        elif width == 3:
            triples = np.frombuffer(payload, dtype=np.uint8).reshape(-1, 3)
            values = (
                triples[:, 0].astype(np.int32)
                | (triples[:, 1].astype(np.int32) << 8)
                | (triples[:, 2].astype(np.int32) << 16)
            )
            values = (values ^ 0x800000) - 0x800000
            samples = values.astype(np.float32) / 8388608.0
        else:
            samples = np.frombuffer(payload, dtype="<i4").astype(np.float32) / 2147483648.0
        if samples.size % channels:
            raise ValueError("sample count is not divisible by channel count")
        mono = samples.reshape(-1, channels).mean(axis=1, dtype=np.float32)
    except (ValueError, MemoryError) as exc:
        raise InvalidAudioFileError(f"WAV PCM payload is invalid: {exc}") from exc
    duration = frame_count / sample_rate
    return _WaveAudio(np.ascontiguousarray(mono), sample_rate, duration)


def _run_official_inference(
    model: Any,
    audio: _WaveAudio,
    runtime: _Runtime,
    provider: str,
) -> str:
    torch = runtime.torch
    waveform = torch.from_numpy(audio.samples).to(dtype=torch.float32).unsqueeze(0)
    if audio.sample_rate != SAMPLE_RATE:
        waveform = runtime.torchaudio.functional.resample(
            waveform, audio.sample_rate, SAMPLE_RATE
        )
    waveform = waveform.squeeze(0).to(provider)
    length = torch.tensor([waveform.numel()], dtype=torch.long, device=provider)
    waveform = waveform.unsqueeze(0)
    inner = getattr(model, "model", None)
    if inner is None or not hasattr(inner, "forward") or not hasattr(inner, "_decode"):
        raise RuntimeError("Official GigaAM model does not expose its documented ASR core.")
    with torch.inference_mode():
        encoded, encoded_length = inner.forward(waveform, length)
        decoded = inner._decode(encoded, encoded_length, length, False)
    if not decoded:
        return ""
    # Official _decode already removes blank labels and collapses repeats.
    return str(decoded[0][0]).strip()


class GigaAMMultilingualCtcRecognizer:
    """Recognize short WAV files with the immutable official Large CTC snapshot."""

    model_id = GIGAAM_MULTILINGUAL_MODEL_ID
    variant = GIGAAM_MULTILINGUAL_VARIANT
    revision = GIGAAM_MULTILINGUAL_REVISION

    def __init__(
        self,
        model_name: str = DEFAULT_ASR_MODEL,
        provider: str = DEFAULT_PROVIDER,
        *,
        snapshot_path: Path | None = None,
        clock: Callable[[], float] = time.perf_counter,
        runtime_loader: Callable[[], _Runtime] = _import_runtime,
        inference_runner: Callable[[Any, _WaveAudio, _Runtime, str], str] = _run_official_inference,
    ) -> None:
        if model_name != GIGAAM_MULTILINGUAL_MODEL_ID:
            raise ModelLoadError(
                "GigaAM Multilingual Large CTC uses only the pinned model ID "
                f"{GIGAAM_MULTILINGUAL_MODEL_ID!r}; received {model_name!r}."
            )
        self.model_name = model_name
        self.provider = _normalize_provider(provider)
        self._snapshot_path = snapshot_path
        self._clock = clock
        self._runtime_loader = runtime_loader
        self._inference_runner = inference_runner
        self._runtime: _Runtime | None = None
        self._model: Any | None = None
        self._model_load_seconds = 0.0
        self.model_load_count = 0
        self.last_metrics: RecognitionMetrics | None = None

    @property
    def model_load_seconds(self) -> float:
        return self._model_load_seconds

    def _resolve_snapshot(self) -> Path:
        if self._snapshot_path is not None:
            return _validate_snapshot(self._snapshot_path)
        try:
            return _validate_snapshot(resolve_model_snapshot(_official_spec()))
        except ModelAssetError as exc:
            raise ModelLoadError(str(exc)) from exc

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        snapshot = self._resolve_snapshot()
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        runtime = self._runtime_loader()
        _validate_runtime(runtime)
        started = self._clock()
        try:
            with _official_remote_code_imports(runtime):
                model = runtime.transformers.AutoModel.from_pretrained(
                    str(snapshot),
                    revision=GIGAAM_MULTILINGUAL_REVISION,
                    trust_remote_code=True,
                    local_files_only=True,
                )
            model.eval()
            model.to(self.provider)
        except (ModelLoadError, ProviderUnavailableError):
            raise
        except Exception as exc:
            raise ModelLoadError(
                "Unable to load the pinned official GigaAM Multilingual Large CTC "
                f"snapshot on {self.provider}: {exc}"
            ) from exc
        self._model_load_seconds = self._clock() - started
        self._runtime = runtime
        self._model = model
        self.model_load_count += 1
        return model

    def prepare(self) -> float:
        self._load_model()
        return self._model_load_seconds

    @staticmethod
    def _validate_path(path: Path) -> Path:
        resolved = path.expanduser().resolve()
        if not resolved.exists():
            raise InvalidAudioFileError(f"WAV file does not exist: {path.name}")
        if not resolved.is_file():
            raise InvalidAudioFileError(f"Audio path is not a regular file: {path.name}")
        if resolved.suffix.casefold() != ".wav":
            raise InvalidAudioFileError(f"Only .wav files are supported: {path.name}")
        return resolved

    def transcribe_file(self, path: Path) -> str:
        resolved = self._validate_path(path)
        audio = _read_pcm_wav(resolved)
        if audio.duration_seconds > MAX_SHORT_AUDIO_SECONDS:
            raise AudioTranscriptionError(
                "GigaAM Multilingual short-file recognition accepts at most 25 seconds; "
                "keep using the existing Silero VAD segmentation for longer audio."
            )
        model = self._load_model()
        started = self._clock()
        try:
            text = (
                ""
                if audio.samples.size == 0
                else self._inference_runner(
                    model, audio, self._runtime, self.provider  # type: ignore[arg-type]
                )
            )
        except Exception as exc:
            if isinstance(exc, AudioTranscriptionError):
                raise
            raise AudioTranscriptionError(
                f"Unable to recognize WAV audio {resolved.name!r}: {exc}"
            ) from exc
        recognition_seconds = self._clock() - started
        duration = audio.duration_seconds
        self.last_metrics = RecognitionMetrics(
            audio_duration_seconds=duration,
            model_load_seconds=self._model_load_seconds,
            recognition_seconds=recognition_seconds,
            rtf=recognition_seconds / duration if duration > 0 else None,
        )
        text = str(text).strip()
        if not text:
            warnings.warn(
                "The GigaAM Multilingual ASR model returned an empty transcription.",
                RuntimeWarning,
                stacklevel=2,
            )
        return text
