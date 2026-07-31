from __future__ import annotations

import ast
import importlib
import json
import logging
import runpy
import sys
import types
from pathlib import Path

import pytest

from live_subtitles import diagnostic_logging, frozen_entry, runtime_paths
from live_subtitles.config import hugging_face_cache_dir

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _close_test_logger() -> None:
    logger = logging.getLogger(diagnostic_logging.LOGGER_NAME)
    for handler in tuple(logger.handlers):
        if getattr(handler, "_ru_zh_handler", False):
            logger.removeHandler(handler)
            handler.close()


def test_freeze_support_is_first_runtime_action_before_project_dispatch() -> None:
    entrypoint = PROJECT_ROOT / "packaging" / "entrypoint.py"
    tree = ast.parse(entrypoint.read_text(encoding="utf-8"))
    top_level_live_imports = [
        node
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        and any(alias.name.startswith("live_subtitles") for alias in node.names)
    ]
    assert top_level_live_imports == []
    guard = next(node for node in tree.body if isinstance(node, ast.If))
    first_call = guard.body[0]
    assert isinstance(first_call, ast.Expr)
    assert isinstance(first_call.value, ast.Call)
    assert ast.unparse(first_call.value.func) == "multiprocessing.freeze_support"


def test_frozen_child_arguments_are_intercepted_before_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ChildIntercepted(RuntimeError):
        pass

    fake_multiprocessing = types.ModuleType("multiprocessing")

    def intercept() -> None:
        raise ChildIntercepted

    fake_multiprocessing.freeze_support = intercept  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "multiprocessing", fake_multiprocessing)
    monkeypatch.delitem(sys.modules, "live_subtitles.frozen_entry", raising=False)
    monkeypatch.setattr(sys, "argv", ["ru-zh-subtitles.exe", "--multiprocessing-fork"])
    with pytest.raises(ChildIntercepted):
        runpy.run_path(
            str(PROJECT_ROOT / "packaging" / "entrypoint.py"),
            run_name="__main__",
        )
    assert "live_subtitles.frozen_entry" not in sys.modules


def test_console_no_arguments_uses_existing_cli_help(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: list[list[str]] = []
    cli = importlib.import_module("live_subtitles.cli")
    monkeypatch.setattr(cli, "main", lambda argv: received.append(list(argv)) or 0)
    result = frozen_entry.run_frozen(
        [], executable=Path("C:/bundle/ru-zh-subtitles-console.exe")
    )
    assert result == 0
    assert received == [["--help"]]


def test_windowed_no_arguments_uses_live_overlay_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    received: list[list[str]] = []
    cli = importlib.import_module("live_subtitles.cli")
    monkeypatch.setattr(cli, "main", lambda argv: received.append(list(argv)) or 0)
    monkeypatch.setenv("RU_ZH_LAUNCH_MODE", "windowed")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(sys, "stdin", None)
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    _close_test_logger()
    try:
        result = frozen_entry.run_frozen([])
    finally:
        _close_test_logger()
    assert result == 0
    assert received == [[
        "live-overlay",
        "--translation-device",
        "cpu",
        "--offline",
        "--no-auto-start",
    ]]
    assert (tmp_path / "ru-zh-live-subtitles" / "logs" / "application.log").is_file()


def test_windowed_none_stream_sink_behaves_like_text_stream() -> None:
    stream = diagnostic_logging.safe_text_stream(None)
    assert stream.encoding == "utf-8"
    text = "字幕 is deliberately discarded"
    assert stream.write(text) == len(text)
    stream.flush()


def test_frozen_resource_helper_is_centralized(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bundle = tmp_path / "bundle"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    assert runtime_paths.bundled_resource_path("docs/help.txt") == (
        bundle / "docs" / "help.txt"
    ).resolve()
    occurrences = []
    for path in (PROJECT_ROOT / "src").rglob("*.py"):
        if "_MEIPASS" in path.read_text(encoding="utf-8"):
            occurrences.append(path.name)
    assert occurrences == ["runtime_paths.py"]


def test_model_cache_never_uses_bundle_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bundle = tmp_path / "bundle"
    cache_home = tmp_path / "hf-user-data"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setenv("HF_HOME", str(cache_home))
    assert hugging_face_cache_dir() == cache_home / "hub"
    assert bundle not in hugging_face_cache_dir().parents


def test_local_app_data_log_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert runtime_paths.log_directory() == (
        tmp_path / "ru-zh-live-subtitles" / "logs"
    )


def test_diagnostic_log_rotates_and_redacts_sensitive_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("HF_TOKEN", "hf_abcdefghijklmnop")
    _close_test_logger()
    try:
        logger = diagnostic_logging.configure_diagnostic_logging()
        logger.info("startup path=%s token=%s", Path.home(), "hf_abcdefghijklmnop")
        for handler in logger.handlers:
            handler.flush()
        log_path = runtime_paths.log_directory() / diagnostic_logging.LOG_FILENAME
        content = log_path.read_text(encoding="utf-8")
    finally:
        _close_test_logger()
    assert str(Path.home()) not in content
    assert "hf_abcdefghijklmnop" not in content
    assert "<redacted-path>" in content
    assert "<redacted-token>" in content
    assert diagnostic_logging.MAX_LOG_BYTES == 1024 * 1024
    assert diagnostic_logging.LOG_BACKUP_COUNT == 2


def test_gui_logging_never_passes_caption_text_to_logger() -> None:
    source = (PROJECT_ROOT / "src" / "live_subtitles" / "gui" / "app.py").read_text(
        encoding="utf-8"
    )
    assert "_logger.info(event.russian_text" not in source
    assert "_logger.info(event.chinese_text" not in source
    assert "_logger.error(event.message" not in source
    exit_metrics_source = source.split("def _log_live_exit_metrics", 1)[1].split(
        "def _print_live_worker_summary", 1
    )[0]
    assert "russian_text" not in exit_metrics_source
    assert "chinese_text" not in exit_metrics_source


def test_torch_hook_keeps_runtime_dtype_table_but_filters_private_tests() -> None:
    source = (PROJECT_ROOT / "packaging" / "hooks" / "hook-torch.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    predicate = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_runtime_torch_module"
    )
    isolated = ast.Module(body=[predicate], type_ignores=[])
    namespace: dict[str, object] = {}
    exec(compile(isolated, "hook-torch.py", "exec"), namespace)
    runtime_filter = namespace["_runtime_torch_module"]
    assert callable(runtime_filter)
    assert runtime_filter("torch.testing._internal.common_dtype") is True
    assert runtime_filter("torch.testing._internal.common_utils") is False
    assert runtime_filter("torch.nn.functional") is True


@pytest.mark.parametrize("name", ["console.spec", "windowed.spec"])
def test_spec_has_valid_python_syntax_and_safe_onedir_settings(name: str) -> None:
    source = (PROJECT_ROOT / "packaging" / name).read_text(encoding="utf-8")
    compile(source, name, "exec")
    assert "COLLECT(" in source
    assert "upx=False" in source
    assert "strip=False" in source
    assert "debug=False" in source
    assert "onefile" not in source.lower()


def test_manifest_template_has_no_machine_absolute_paths() -> None:
    template = json.loads(
        (PROJECT_ROOT / "packaging" / "manifest-template.json").read_text(
            encoding="utf-8"
        )
    )
    serialized = json.dumps(template)
    assert "C:\\Users\\" not in serialized
    assert str(PROJECT_ROOT) not in serialized
    assert template["models_bundled"] is False
    assert template["signing_status"] == "unsigned"


def test_generated_packaging_manifest_defaults_to_ignored_data_directory(
    tmp_path: Path,
) -> None:
    namespace = runpy.run_path(str(PROJECT_ROOT / "packaging" / "build_manifest.py"))
    assert namespace["DEFAULT_MANIFEST_PATH"] == Path(
        "data/packaging-manifests/packaging-manifest.json"
    )

    output = tmp_path / "nested" / "manifest.json"
    namespace["write_manifest"](output, {"models_bundled": False})
    assert json.loads(output.read_text(encoding="utf-8")) == {
        "models_bundled": False
    }
