"""Lazy direct-Transformers wrapper for Russian-to-Chinese T5 translation."""

from __future__ import annotations

import importlib
import time
import warnings
from dataclasses import dataclass
from typing import Any, Callable, Literal

from ..config import DEFAULT_TRANSLATION_MODEL

DeviceChoice = Literal["auto", "cpu", "cuda"]


class TranslationError(RuntimeError):
    """Base class for user-facing translation errors."""


class InvalidTranslationInputError(TranslationError):
    """Raised when the source text or generation settings are invalid."""


class TranslationDeviceError(TranslationError):
    """Raised when the requested compute device is unavailable."""


class TranslationModelError(TranslationError):
    """Raised when model loading or generation fails."""


@dataclass(frozen=True)
class TranslationMetrics:
    tokenizer_load_seconds: float
    model_load_seconds: float
    total_load_seconds: float
    translation_seconds: float
    input_characters: int
    output_characters: int
    device: str
    dtype: str
    peak_cuda_memory_bytes: int
    first_call: bool


class T5RuZhTranslator:
    """Translate Russian text to Chinese with one lazily loaded T5 instance."""

    def __init__(
        self,
        model_name: str = DEFAULT_TRANSLATION_MODEL,
        *,
        device: DeviceChoice = "auto",
        num_beams: int = 1,
        max_new_tokens: int = 256,
        max_input_characters: int = 2_000,
        max_input_tokens: int = 512,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        if device not in {"auto", "cpu", "cuda"}:
            raise TranslationDeviceError("Device must be one of: auto, cpu, cuda.")
        if num_beams <= 0:
            raise InvalidTranslationInputError("num_beams must be greater than 0.")
        if max_new_tokens <= 0:
            raise InvalidTranslationInputError("max_new_tokens must be greater than 0.")
        if max_input_characters <= 0 or max_input_tokens <= 0:
            raise InvalidTranslationInputError("Input limits must be greater than 0.")

        self.model_name = model_name
        self.requested_device = device
        self.num_beams = num_beams
        self.max_new_tokens = max_new_tokens
        self.max_input_characters = max_input_characters
        self.max_input_tokens = max_input_tokens
        self._clock = clock
        self._torch: Any | None = None
        self._tokenizer: Any | None = None
        self._model: Any | None = None
        self.actual_device: str | None = None
        self.dtype: str | None = None
        self._tokenizer_load_seconds = 0.0
        self._model_load_seconds = 0.0
        self._total_load_seconds = 0.0
        self.last_metrics: TranslationMetrics | None = None

    @staticmethod
    def _cuda_sync(torch_module: Any, device: str | None) -> None:
        if device == "cuda":
            torch_module.cuda.synchronize()

    def _resolve_device(self, torch_module: Any) -> str:
        cuda_available = bool(torch_module.cuda.is_available())
        if self.requested_device == "cuda" and not cuda_available:
            raise TranslationDeviceError("CUDA was requested but torch.cuda.is_available() is false.")
        if self.requested_device == "auto":
            return "cuda" if cuda_available else "cpu"
        return self.requested_device

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            torch_module = importlib.import_module("torch")
            transformers = importlib.import_module("transformers")
        except Exception as exc:
            raise TranslationModelError(f"Translation dependencies are unavailable: {exc}") from exc

        actual_device = self._resolve_device(torch_module)
        dtype_name = "float16" if actual_device == "cuda" else "float32"
        dtype = getattr(torch_module, dtype_name)
        if actual_device == "cuda":
            torch_module.cuda.reset_peak_memory_stats()
            self._cuda_sync(torch_module, actual_device)

        load_started = self._clock()
        try:
            tokenizer = transformers.AutoTokenizer.from_pretrained(
                self.model_name,
                trust_remote_code=False,
            )
        except Exception as exc:
            raise TranslationModelError(
                f"Unable to load tokenizer for {self.model_name!r}: {exc}"
            ) from exc
        tokenizer_finished = self._clock()

        try:
            model = transformers.AutoModelForSeq2SeqLM.from_pretrained(
                self.model_name,
                dtype=dtype,
                use_safetensors=True,
                trust_remote_code=False,
            )
            model.to(actual_device)
            model.eval()
            self._cuda_sync(torch_module, actual_device)
        except Exception as exc:
            raise TranslationModelError(
                f"Unable to load translation model {self.model_name!r} on {actual_device}: {exc}"
            ) from exc
        model_finished = self._clock()

        self._torch = torch_module
        self._tokenizer = tokenizer
        self._model = model
        self.actual_device = actual_device
        self.dtype = dtype_name
        self._tokenizer_load_seconds = tokenizer_finished - load_started
        self._model_load_seconds = model_finished - tokenizer_finished
        self._total_load_seconds = model_finished - load_started

    def _validate_text(self, text: str) -> str:
        if text is None:
            raise InvalidTranslationInputError("Translation text must not be None.")
        if not isinstance(text, str):
            raise InvalidTranslationInputError("Translation text must be a string.")
        stripped = text.strip()
        if not stripped:
            raise InvalidTranslationInputError("Translation text must not be empty or whitespace-only.")
        if len(stripped) > self.max_input_characters:
            raise InvalidTranslationInputError(
                f"Translation text has {len(stripped)} characters; maximum is {self.max_input_characters}."
            )
        return stripped

    def translate(self, text: str) -> str:
        source_text = self._validate_text(text)
        first_call = self._model is None
        self._load()
        assert self._torch is not None
        assert self._tokenizer is not None
        assert self._model is not None
        assert self.actual_device is not None
        assert self.dtype is not None

        prompt = f"translate to zh: {source_text}"
        try:
            encoded = self._tokenizer(prompt, return_tensors="pt", truncation=False)
            token_count = int(encoded["input_ids"].shape[-1])
        except Exception as exc:
            raise TranslationModelError(f"Unable to tokenize translation input: {exc}") from exc
        if token_count > self.max_input_tokens:
            raise InvalidTranslationInputError(
                f"Translation input has {token_count} tokens; maximum is {self.max_input_tokens}."
            )
        try:
            device_inputs = {name: tensor.to(self.actual_device) for name, tensor in encoded.items()}
            self._cuda_sync(self._torch, self.actual_device)
            started = self._clock()
            with self._torch.inference_mode():
                generated = self._model.generate(
                    **device_inputs,
                    max_new_tokens=self.max_new_tokens,
                    num_beams=self.num_beams,
                    do_sample=False,
                )
            self._cuda_sync(self._torch, self.actual_device)
            translation_seconds = self._clock() - started
            output = self._tokenizer.batch_decode(generated, skip_special_tokens=True)[0].strip()
        except TranslationError:
            raise
        except Exception as exc:
            raise TranslationModelError(f"Translation generation failed: {exc}") from exc

        if not output:
            warnings.warn("The translation model returned empty text.", RuntimeWarning, stacklevel=2)
        peak_memory = (
            int(self._torch.cuda.max_memory_allocated())
            if self.actual_device == "cuda"
            else 0
        )
        self.last_metrics = TranslationMetrics(
            tokenizer_load_seconds=self._tokenizer_load_seconds,
            model_load_seconds=self._model_load_seconds,
            total_load_seconds=self._total_load_seconds,
            translation_seconds=translation_seconds,
            input_characters=len(source_text),
            output_characters=len(output),
            device=self.actual_device,
            dtype=self.dtype,
            peak_cuda_memory_bytes=peak_memory,
            first_call=first_call,
        )
        return output
