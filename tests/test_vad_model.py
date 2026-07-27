from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from live_subtitles.realtime.vad_model import SileroOnnxVad, VadInferenceError


class FakeSession:
    def __init__(self, probabilities: list[float] | None = None) -> None:
        self.probabilities = iter(probabilities or [0.1, 0.2, 0.3])
        self.states: list[np.ndarray] = []
        self.inputs: list[np.ndarray] = []

    @staticmethod
    def get_inputs() -> list[SimpleNamespace]:
        return [
            SimpleNamespace(name="input", shape=[None, None], type="tensor(float)"),
            SimpleNamespace(name="state", shape=[2, None, 128], type="tensor(float)"),
            SimpleNamespace(name="sr", shape=[], type="tensor(int64)"),
        ]

    @staticmethod
    def get_outputs() -> list[SimpleNamespace]:
        return [
            SimpleNamespace(name="output", shape=[None, 1], type="tensor(float)"),
            SimpleNamespace(name="stateN", shape=[None, None, None], type="tensor(float)"),
        ]

    def run(self, names: list[str], inputs: dict[str, np.ndarray]) -> list[np.ndarray]:
        assert names == ["output", "stateN"]
        self.states.append(inputs["state"].copy())
        self.inputs.append(inputs["input"].copy())
        probability = next(self.probabilities)
        return [
            np.asarray([[probability]], dtype=np.float32),
            inputs["state"] + np.float32(1.0),
        ]


def create_model(tmp_path: Path, session: FakeSession) -> tuple[SileroOnnxVad, list[Path]]:
    model_path = tmp_path / "model.onnx"
    model_path.write_bytes(b"not-loaded-by-fake")
    creations: list[Path] = []

    def factory(path: Path, provider: str) -> FakeSession:
        assert provider == "CPUExecutionProvider"
        creations.append(path)
        return session

    return SileroOnnxVad(model_path, session_factory=factory), creations


def test_import_and_construction_do_not_create_session(tmp_path: Path) -> None:
    model, creations = create_model(tmp_path, FakeSession())
    assert creations == []
    assert model.session_creation_count == 0


def test_prepare_is_lazy_and_idempotent(tmp_path: Path) -> None:
    model, creations = create_model(tmp_path, FakeSession())
    model.prepare()
    model.prepare()
    assert len(creations) == 1
    assert model.session_creation_count == 1
    assert [item.name for item in model.inputs] == ["input", "state", "sr"]
    assert [item.name for item in model.outputs] == ["output", "stateN"]


def test_state_and_context_continue_then_reset(tmp_path: Path) -> None:
    session = FakeSession()
    model, _ = create_model(tmp_path, session)
    first = np.linspace(-0.5, 0.5, 512, dtype=np.float32)
    second = np.full(512, 0.25, dtype=np.float32)
    assert model.speech_probability(first) == pytest.approx(0.1)
    assert model.speech_probability(second) == pytest.approx(0.2)
    assert np.count_nonzero(session.states[0]) == 0
    assert np.all(session.states[1] == 1.0)
    assert session.inputs[0].shape == (1, 576)
    assert np.array_equal(session.inputs[1][0, :64], first[-64:])
    model.reset()
    model.speech_probability(first)
    assert np.count_nonzero(session.states[2]) == 0
    assert np.count_nonzero(session.inputs[2][0, :64]) == 0


@pytest.mark.parametrize(
    ("chunk", "message"),
    [
        (np.zeros(512, dtype=np.float64), "dtype"),
        (np.zeros(511, dtype=np.float32), "512"),
        (np.zeros((1, 512), dtype=np.float32), "one-dimensional"),
        (np.full(512, np.nan, dtype=np.float32), "NaN"),
        (np.full(512, np.inf, dtype=np.float32), "NaN"),
        (np.full(512, 1.1, dtype=np.float32), r"\[-1, 1\]"),
    ],
)
def test_invalid_chunks_are_rejected(
    chunk: np.ndarray,
    message: str,
    tmp_path: Path,
) -> None:
    model, creations = create_model(tmp_path, FakeSession())
    with pytest.raises(VadInferenceError, match=message):
        model.speech_probability(chunk)
    assert creations == []


@pytest.mark.parametrize("probability", [-0.1, 1.1, float("nan")])
def test_invalid_probability_is_rejected(probability: float, tmp_path: Path) -> None:
    model, _ = create_model(tmp_path, FakeSession([probability]))
    with pytest.raises(VadInferenceError, match="invalid speech probability"):
        model.speech_probability(np.zeros(512, dtype=np.float32))


def test_vad_source_does_not_import_forbidden_packages() -> None:
    source_dir = Path(__file__).parents[1] / "src" / "live_subtitles" / "realtime"
    source = "\n".join(path.read_text(encoding="utf-8") for path in source_dir.glob("*.py"))
    assert "import torch" not in source
    assert "import torchaudio" not in source
    assert "import silero_vad" not in source
    assert "C:\\Users\\seren" not in source
