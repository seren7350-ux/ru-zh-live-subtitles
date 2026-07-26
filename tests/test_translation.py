from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from live_subtitles.translation import t5_ru_zh
from live_subtitles.translation.t5_ru_zh import (
    InvalidTranslationInputError,
    T5RuZhTranslator,
    TranslationDeviceError,
    TranslationModelError,
)


class FakeTensor:
    def __init__(self, token_count: int = 5) -> None:
        self.shape = (1, token_count)
        self.devices: list[str] = []

    def to(self, device: str) -> "FakeTensor":
        self.devices.append(device)
        return self


class FakeTokenizer:
    def __init__(self, output: str = "  今天我们讨论线性算子。  ", token_count: int = 5) -> None:
        self.output = output
        self.token_count = token_count
        self.prompts: list[str] = []

    def __call__(self, prompt: str, **kwargs: object) -> dict[str, FakeTensor]:
        self.prompts.append(prompt)
        assert kwargs == {"return_tensors": "pt", "truncation": False}
        return {"input_ids": FakeTensor(self.token_count), "attention_mask": FakeTensor(self.token_count)}

    def batch_decode(self, generated: object, **kwargs: object) -> list[str]:
        assert kwargs == {"skip_special_tokens": True}
        return [self.output]


class FakeModel:
    def __init__(self, *, generation_error: Exception | None = None) -> None:
        self.to_devices: list[str] = []
        self.eval_calls = 0
        self.generate_calls: list[dict[str, object]] = []
        self.generation_error = generation_error

    def to(self, device: str) -> "FakeModel":
        self.to_devices.append(device)
        return self

    def eval(self) -> None:
        self.eval_calls += 1

    def generate(self, **kwargs: object) -> list[list[int]]:
        self.generate_calls.append(kwargs)
        if self.generation_error:
            raise self.generation_error
        return [[1, 2, 3]]


class FakeCuda:
    def __init__(self, available: bool) -> None:
        self.available = available
        self.sync_calls = 0
        self.reset_calls = 0

    def is_available(self) -> bool:
        return self.available

    def synchronize(self) -> None:
        self.sync_calls += 1

    def reset_peak_memory_stats(self) -> None:
        self.reset_calls += 1

    @staticmethod
    def max_memory_allocated() -> int:
        return 512 * 1024 * 1024

    @staticmethod
    def get_device_name(_: int) -> str:
        return "Fake GPU"


def fake_torch(cuda_available: bool) -> SimpleNamespace:
    @contextmanager
    def inference_mode():
        yield

    return SimpleNamespace(
        __version__="test",
        cuda=FakeCuda(cuda_available),
        float16="fake-float16",
        float32="fake-float32",
        inference_mode=inference_mode,
    )


def install_fake_modules(
    monkeypatch: pytest.MonkeyPatch,
    *,
    cuda_available: bool,
    tokenizer: FakeTokenizer | None = None,
    model: FakeModel | None = None,
    model_load_error: Exception | None = None,
) -> tuple[SimpleNamespace, FakeTokenizer, FakeModel, list[dict[str, object]], list[dict[str, object]]]:
    torch_module = fake_torch(cuda_available)
    tokenizer = tokenizer or FakeTokenizer()
    model = model or FakeModel()
    tokenizer_loads: list[dict[str, object]] = []
    model_loads: list[dict[str, object]] = []

    class AutoTokenizer:
        @staticmethod
        def from_pretrained(name: str, **kwargs: object) -> FakeTokenizer:
            tokenizer_loads.append({"name": name, **kwargs})
            return tokenizer

    class AutoModel:
        @staticmethod
        def from_pretrained(name: str, **kwargs: object) -> FakeModel:
            model_loads.append({"name": name, **kwargs})
            if model_load_error:
                raise model_load_error
            return model

    transformers_module = SimpleNamespace(
        __version__="test",
        AutoTokenizer=AutoTokenizer,
        AutoModelForSeq2SeqLM=AutoModel,
    )

    def fake_import(name: str):
        if name == "torch":
            return torch_module
        if name == "transformers":
            return transformers_module
        raise ImportError(name)

    monkeypatch.setattr(t5_ru_zh.importlib, "import_module", fake_import)
    return torch_module, tokenizer, model, tokenizer_loads, model_loads


def test_import_and_construction_do_not_load_model(monkeypatch: pytest.MonkeyPatch) -> None:
    imports: list[str] = []
    monkeypatch.setattr(t5_ru_zh.importlib, "import_module", lambda name: imports.append(name))
    T5RuZhTranslator()
    assert imports == []


@pytest.mark.parametrize("text", [None, "", "   \t\r\n"])
def test_empty_text_is_rejected_before_loading(text: str | None, monkeypatch: pytest.MonkeyPatch) -> None:
    imports: list[str] = []
    monkeypatch.setattr(t5_ru_zh.importlib, "import_module", lambda name: imports.append(name))
    with pytest.raises(InvalidTranslationInputError):
        T5RuZhTranslator().translate(text)  # type: ignore[arg-type]
    assert imports == []


def test_model_is_lazy_loaded_once_and_generation_settings_are_forwarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, tokenizer, model, tokenizer_loads, model_loads = install_fake_modules(
        monkeypatch,
        cuda_available=False,
    )
    times = iter([1.0, 1.2, 1.8, 2.0, 2.4, 3.0, 3.3])
    translator = T5RuZhTranslator(num_beams=4, max_new_tokens=77, clock=lambda: next(times))

    assert tokenizer_loads == []
    assert translator.translate("Сегодня лекция.") == "今天我们讨论线性算子。"
    assert translator.last_metrics is not None
    assert translator.last_metrics.first_call is True
    assert translator.translate("Второе предложение.") == "今天我们讨论线性算子。"

    assert len(tokenizer_loads) == 1
    assert len(model_loads) == 1
    assert tokenizer.prompts == [
        "translate to zh: Сегодня лекция.",
        "translate to zh: Второе предложение.",
    ]
    assert model_loads[0]["trust_remote_code"] is False
    assert model_loads[0]["use_safetensors"] is True
    assert model_loads[0]["dtype"] == "fake-float32"
    assert model.to_devices == ["cpu"]
    assert model.eval_calls == 1
    assert model.generate_calls[0]["do_sample"] is False
    assert model.generate_calls[0]["max_new_tokens"] == 77
    assert model.generate_calls[0]["num_beams"] == 4
    assert translator.actual_device == "cpu"
    assert translator.dtype == "float32"
    assert translator.last_metrics is not None
    assert translator.last_metrics.first_call is False


def test_unavailable_cuda_request_is_rejected_before_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, _, tokenizer_loads, model_loads = install_fake_modules(monkeypatch, cuda_available=False)
    with pytest.raises(TranslationDeviceError, match="CUDA was requested"):
        T5RuZhTranslator(device="cuda").translate("Текст")
    assert tokenizer_loads == []
    assert model_loads == []


def test_auto_selects_cuda_and_float16(monkeypatch: pytest.MonkeyPatch) -> None:
    torch_module, _, _, _, model_loads = install_fake_modules(monkeypatch, cuda_available=True)
    times = iter([1.0, 1.1, 1.5, 2.0, 2.2])
    translator = T5RuZhTranslator(device="auto", clock=lambda: next(times))
    translator.translate("Текст")
    assert translator.actual_device == "cuda"
    assert translator.dtype == "float16"
    assert model_loads[0]["dtype"] == "fake-float16"
    assert torch_module.cuda.reset_calls == 1
    assert torch_module.cuda.sync_calls >= 4
    assert translator.last_metrics is not None
    assert translator.last_metrics.peak_cuda_memory_bytes == 512 * 1024 * 1024


def test_auto_selects_cpu_without_cuda(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_modules(monkeypatch, cuda_available=False)
    times = iter([1.0, 1.1, 1.5, 2.0, 2.2])
    translator = T5RuZhTranslator(device="auto", clock=lambda: next(times))
    translator.translate("Текст")
    assert translator.actual_device == "cpu"
    assert translator.dtype == "float32"


def test_generation_exception_is_user_facing(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_modules(
        monkeypatch,
        cuda_available=False,
        model=FakeModel(generation_error=RuntimeError("simulated generation failure")),
    )
    times = iter([1.0, 1.1, 1.5, 2.0])
    with pytest.raises(TranslationModelError, match="Translation generation failed"):
        T5RuZhTranslator(clock=lambda: next(times)).translate("Текст")


def test_model_load_exception_is_user_facing(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_modules(
        monkeypatch,
        cuda_available=False,
        model_load_error=RuntimeError("simulated model load failure"),
    )
    times = iter([1.0, 1.1])
    with pytest.raises(TranslationModelError, match="Unable to load translation model"):
        T5RuZhTranslator(clock=lambda: next(times)).translate("Текст")


def test_too_many_characters_is_rejected_before_loading(monkeypatch: pytest.MonkeyPatch) -> None:
    imports: list[str] = []
    monkeypatch.setattr(t5_ru_zh.importlib, "import_module", lambda name: imports.append(name))
    with pytest.raises(InvalidTranslationInputError, match="maximum is 2000"):
        T5RuZhTranslator().translate("я" * 2001)
    assert imports == []


def test_too_many_tokens_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_modules(monkeypatch, cuda_available=False, tokenizer=FakeTokenizer(token_count=513))
    times = iter([1.0, 1.1, 1.5])
    with pytest.raises(InvalidTranslationInputError, match="513 tokens"):
        T5RuZhTranslator(clock=lambda: next(times)).translate("Текст")
