from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from live_subtitles.translation import runtime
from live_subtitles.translation.factory import create_translator
from live_subtitles.translation.m2m100_ru_zh import M2M100RuZhTranslator
from live_subtitles.translation.nllb_ru_zh import NllbRuZhTranslator
from live_subtitles.translation.t5_ru_zh import (
    InvalidTranslationInputError,
    T5RuZhTranslator,
    TranslationDeviceError,
)


class FakeTensor:
    shape = (1, 5)

    def __init__(self) -> None:
        self.devices: list[str] = []

    def to(self, device: str) -> "FakeTensor":
        self.devices.append(device)
        return self


class FakeTokenizer:
    unk_token_id = 0
    init_kwargs = {"_commit_hash": "tokenizer-sha"}

    def __init__(self, target_id: int) -> None:
        self.target_id = target_id
        self.lang_requests: list[str] = []
        self.token_requests: list[str] = []
        self.inputs: list[str] = []

    def get_lang_id(self, language: str) -> int:
        self.lang_requests.append(language)
        return self.target_id

    def convert_tokens_to_ids(self, token: str) -> int:
        self.token_requests.append(token)
        return self.target_id

    def __call__(self, text: str, **kwargs: object) -> dict[str, FakeTensor]:
        self.inputs.append(text)
        assert kwargs == {"return_tensors": "pt", "truncation": False}
        return {"input_ids": FakeTensor(), "attention_mask": FakeTensor()}

    @staticmethod
    def batch_decode(generated: object, **kwargs: object) -> list[str]:
        assert kwargs == {"skip_special_tokens": True}
        return ["  巴拿赫空间中的有界线性算子。  "]


class FakeModel:
    def __init__(self) -> None:
        self.config = SimpleNamespace(_commit_hash="model-revision-sha")
        self.to_devices: list[str] = []
        self.eval_calls = 0
        self.generate_calls: list[dict[str, object]] = []

    def to(self, device: str) -> "FakeModel":
        self.to_devices.append(device)
        return self

    def eval(self) -> None:
        self.eval_calls += 1

    def generate(self, **kwargs: object) -> list[list[int]]:
        self.generate_calls.append(kwargs)
        return [[1, 2]]


class FakeCuda:
    def __init__(self, available: bool) -> None:
        self.available = available

    def is_available(self) -> bool:
        return self.available

    @staticmethod
    def synchronize() -> None:
        return None

    @staticmethod
    def reset_peak_memory_stats() -> None:
        return None

    @staticmethod
    def max_memory_allocated() -> int:
        return 123456


def install_modules(
    monkeypatch: pytest.MonkeyPatch,
    *,
    cuda_available: bool,
    target_id: int,
) -> tuple[FakeTokenizer, FakeModel, list[dict[str, object]], list[dict[str, object]]]:
    tokenizer = FakeTokenizer(target_id)
    model = FakeModel()
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
            return model

    @contextmanager
    def inference_mode():
        yield

    torch_module = SimpleNamespace(
        cuda=FakeCuda(cuda_available),
        float16="float16",
        float32="float32",
        inference_mode=inference_mode,
    )
    transformers_module = SimpleNamespace(
        AutoTokenizer=AutoTokenizer,
        AutoModelForSeq2SeqLM=AutoModel,
    )
    modules = {"torch": torch_module, "transformers": transformers_module}
    monkeypatch.setattr(runtime.importlib, "import_module", lambda name: modules[name])
    return tokenizer, model, tokenizer_loads, model_loads


@pytest.mark.parametrize("translator_class", [M2M100RuZhTranslator, NllbRuZhTranslator])
def test_import_and_construction_are_lazy(
    translator_class: type[object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imports: list[str] = []
    monkeypatch.setattr(runtime.importlib, "import_module", lambda name: imports.append(name))
    translator_class()
    assert imports == []


@pytest.mark.parametrize(
    ("translator_class", "source_language", "target_attribute", "target_language", "target_id"),
    [
        (M2M100RuZhTranslator, "ru", "lang_requests", "zh", 731),
        (NllbRuZhTranslator, "rus_Cyrl", "token_requests", "zho_Hans", 947),
    ],
)
def test_model_loads_once_and_language_generation_settings_are_dynamic(
    translator_class: type[object],
    source_language: str,
    target_attribute: str,
    target_language: str,
    target_id: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokenizer, model, tokenizer_loads, model_loads = install_modules(
        monkeypatch,
        cuda_available=False,
        target_id=target_id,
    )
    times = iter([1.0, 1.2, 1.8, 2.0, 2.4, 3.0, 3.3])
    translator = translator_class(  # type: ignore[call-arg]
        num_beams=4,
        max_new_tokens=77,
        clock=lambda: next(times),
    )

    assert translator.translate("Первый текст") == "巴拿赫空间中的有界线性算子。"  # type: ignore[attr-defined]
    assert translator.translate("Второй текст") == "巴拿赫空间中的有界线性算子。"  # type: ignore[attr-defined]
    assert len(tokenizer_loads) == 1
    assert len(model_loads) == 1
    assert tokenizer_loads[0]["src_lang"] == source_language
    assert tokenizer_loads[0]["trust_remote_code"] is False
    assert model_loads[0]["trust_remote_code"] is False
    assert model_loads[0]["use_safetensors"] is False
    assert getattr(tokenizer, target_attribute) == [target_language, target_language, target_language]
    assert model.generate_calls[0]["forced_bos_token_id"] == target_id
    assert model.generate_calls[0]["do_sample"] is False
    assert model.generate_calls[0]["num_beams"] == 4
    assert model.generate_calls[0]["max_new_tokens"] == 77
    assert model.to_devices == ["cpu"]
    assert translator.revision == "model-revision-sha"  # type: ignore[attr-defined]


def test_factory_returns_all_engines_and_rejects_unknown() -> None:
    assert isinstance(create_translator("t5", None, "cpu", 1, 32), T5RuZhTranslator)
    assert isinstance(create_translator("m2m100", None, "cpu", 1, 32), M2M100RuZhTranslator)
    assert isinstance(create_translator("nllb", None, "cpu", 1, 32), NllbRuZhTranslator)
    with pytest.raises(InvalidTranslationInputError, match="Unknown translation engine"):
        create_translator("invalid", None, "cpu", 1, 32)


def test_cuda_request_is_rejected_and_auto_selects_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, tokenizer_loads, _ = install_modules(monkeypatch, cuda_available=False, target_id=31)
    with pytest.raises(TranslationDeviceError, match="CUDA was requested"):
        M2M100RuZhTranslator(device="cuda").translate("Текст")
    assert tokenizer_loads == []

    times = iter([1.0, 1.1, 1.2, 2.0, 2.1])
    translator = NllbRuZhTranslator(device="auto", clock=lambda: next(times))
    translator.translate("Текст")
    assert translator.actual_device == "cpu"
    assert translator.dtype == "float32"


@pytest.mark.parametrize("translator_class", [M2M100RuZhTranslator, NllbRuZhTranslator])
def test_empty_input_is_rejected_before_import(
    translator_class: type[object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    imports: list[str] = []
    monkeypatch.setattr(runtime.importlib, "import_module", lambda name: imports.append(name))
    with pytest.raises(InvalidTranslationInputError):
        translator_class().translate("   ")  # type: ignore[attr-defined]
    assert imports == []


def test_translation_source_has_no_user_absolute_path() -> None:
    source_dir = Path(__file__).parents[1] / "src" / "live_subtitles" / "translation"
    source = "\n".join(path.read_text(encoding="utf-8") for path in source_dir.glob("*.py"))
    assert "C:\\Users\\seren" not in source
