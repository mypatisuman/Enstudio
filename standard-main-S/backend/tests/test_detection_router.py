"""Detection is pure LLM, with no trained model and no fallback.

Three defects are pinned here.

1. `supports_vision` existed ONLY on OllamaProvider. The three vision-LLM
   detection services call `llm.supports_vision('fast')` before doing any tile
   work, so on the default provider (Anthropic) that call raised
   `AttributeError` and the whole detection pipeline was dead.

2. Three call sites answered "which detector runs?" independently -- main.py
   preferred the LLM services, while api/detect.py and extraction_cli/image.py
   hardwired the CV ones -- so the same drawing produced different results
   depending on the entry point.

3. Trained models were still reachable. The agentic pipeline's `warmup` node
   called `_init_cv_models()`, loading YOLOv8 + RapidOCR + U-Net on every run,
   and an earlier version of the router offered `cv` and `auto` engines that
   fell back to them. Both are gone: the router has ONE engine, a provider that
   cannot see images is a loud failure, and the trained entry points refuse.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

STUDIO = Path(__file__).resolve().parent.parent
if str(STUDIO) not in sys.path:
    sys.path.insert(0, str(STUDIO))

from adapters.llm_provider import LLMProvider  # noqa: E402
from adapters.vision_capability import supports_vision_for  # noqa: E402
from services import detection_router as R  # noqa: E402


@pytest.fixture()
def seeing(monkeypatch):
    """Pretend the configured provider can accept images."""
    monkeypatch.setattr(R, "provider_vision_status", lambda: (True, "stub"))


@pytest.fixture()
def blind(monkeypatch):
    """Pretend the configured provider cannot accept images."""
    monkeypatch.setattr(R, "provider_vision_status", lambda: (False, "stub"))


# ── 1. Every provider answers the vision guard ──────────────────────────────

def test_base_provider_defines_supports_vision():
    assert hasattr(LLMProvider, "supports_vision")


@pytest.mark.parametrize("module_path, cls_name, expected_id", [
    ("adapters.llm_anthropic", "AnthropicProvider", "anthropic"),
    ("adapters.llm_gemini", "GeminiProvider", "gemini"),
])
def test_hosted_providers_declare_their_id(module_path, cls_name, expected_id):
    mod = pytest.importorskip(module_path)
    assert getattr(getattr(mod, cls_name), "provider_name", "") == expected_id


def test_openai_provider_id_follows_the_custom_preset_label():
    from adapters.llm_openai import OpenAIProvider
    assert OpenAIProvider(api_key="x", model="gpt-5.5").provider_name == "openai"
    assert OpenAIProvider(api_key="x", model="grok-4",
                          provider_label="custom:grok").provider_name == "custom:grok"


def test_anthropic_supports_vision_does_not_raise():
    """The exact call the detection services make, on the default provider."""
    from adapters.llm_anthropic import AnthropicProvider
    provider = AnthropicProvider(api_key="unused")
    assert provider.supports_vision("fast") is True
    assert provider.supports_vision("smart") is True


def test_ollama_keeps_its_strict_name_check():
    """Ollama silently ignores images on a text-only model, so unknown names
    must read as text-only there -- the opposite of the hosted default."""
    from adapters.llm_ollama import OllamaProvider
    assert OllamaProvider(model_fast="llama3.2").supports_vision("fast") is False
    assert OllamaProvider(model_fast="llava:13b").supports_vision("fast") is True


@pytest.mark.parametrize("provider, model, expected", [
    ("anthropic", "claude-haiku-4-5-20251001", True),
    ("anthropic", "claude-2.1", False),
    ("gemini", "gemini-2.0-flash", True),
    ("gemini", "text-embedding-004", False),
    ("openai", "gpt-5.5", True),
    ("openai", "gpt-3.5-turbo", False),
    ("custom:deepseek", "deepseek-chat", False),
    ("custom:grok", "grok-4", True),
    ("anthropic", "some-unreleased-model", True),   # permissive default
])
def test_capability_table(provider, model, expected):
    assert supports_vision_for(provider, model) is expected


# ── 2. One engine, no fallback ──────────────────────────────────────────────

def test_only_one_engine_exists():
    assert R.VALID_ENGINES == ("llm",)
    assert R.ENGINE == "llm"


def test_resolved_backend_is_always_the_llm_detectors(seeing):
    backend = R.resolve_backend()
    assert backend.engine == "llm" and backend.is_llm
    assert backend.detect_symbols.__module__ == \
        "services.llm_symbol_detection_service"
    assert backend.detect_text.__module__ == \
        "services.llm_text_detection_service"
    assert backend.detect_lines.__module__ == \
        "services.llm_line_detection_service"


@pytest.mark.parametrize("engine", ["cv", "auto", "yolo", "hybrid"])
def test_asking_for_a_trained_engine_is_refused(engine, seeing):
    """There is no ML engine to ask for -- not even as a fallback."""
    with pytest.raises(ValueError) as exc:
        R.resolve_backend(engine)
    assert "pure LLM" in str(exc.value)


def test_configured_cv_engine_is_ignored_not_honoured(monkeypatch):
    """A leftover STUDIO_DETECTION_ENGINE=cv must not start trained models."""
    monkeypatch.setenv("STUDIO_DETECTION_ENGINE", "cv")
    assert R.configured_engine() == "llm"


def test_configured_auto_engine_is_ignored(monkeypatch):
    monkeypatch.setenv("STUDIO_DETECTION_ENGINE", "auto")
    assert R.configured_engine() == "llm"


def test_llm_engine_is_accepted(monkeypatch):
    monkeypatch.setenv("STUDIO_DETECTION_ENGINE", "LLM")
    assert R.configured_engine() == "llm"


def test_no_vision_fails_loudly_instead_of_falling_back(blind):
    with pytest.raises(R.VisionUnavailable) as exc:
        R.resolve_backend()
    message = str(exc.value)
    assert "no ML fallback" in message
    assert "vision-capable" in message


def test_provider_vision_probe_never_raises(monkeypatch):
    def _boom():
        raise RuntimeError("no provider configured")
    monkeypatch.setattr("adapters.llm_factory.get_provider", _boom)
    has_vision, why = R.provider_vision_status()
    assert has_vision is False and "unavailable" in why


def test_describe_backend_never_raises(blind):
    info = R.describe_backend()
    assert info["resolved"] is None
    assert info["ml_fallback"] is False
    assert "reason" in info


def test_describe_backend_reports_no_ml_fallback(seeing):
    info = R.describe_backend()
    assert info["resolved"] == "llm"
    assert info["ml_fallback"] is False


# ── 3. Legacy ML modules are completely purged ─────────────────────────────

@pytest.mark.parametrize("module_path", [
    "services.detection_service",
    "services.text_detection_service",
    "services.line_detection_service",
    "services._ml_disabled",
])
def test_legacy_ml_modules_do_not_exist(module_path):
    """The legacy ML modules were completely purged in favor of pure LLM + services.geometry."""
    import importlib
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module_path)


def test_geometry_helpers_still_work():
    """The geometry helpers in services.geometry are reused by the vision-LLM
    detectors without any ML modules."""
    from services.geometry.symbol_geometry import _tile_coords, _class_aware_nms
    from services.geometry.line_geometry import _classify_direction
    from services.geometry.text_geometry import _is_valid_text
    assert len(_tile_coords(2000, 1500)) > 0
    assert callable(_class_aware_nms)
    assert callable(_classify_direction)
    assert callable(_is_valid_text)


# ── 4. No ML package is ever loaded ─────────────────────────────────────────

def test_no_ml_package_is_imported_by_the_detection_path(seeing):
    """The strongest available guarantee: import and resolve the whole
    detection stack, then assert no trained-model package is in sys.modules."""
    R.resolve_backend()
    import services.llm_symbol_detection_service   # noqa: F401
    import services.llm_text_detection_service     # noqa: F401
    import services.llm_line_detection_service     # noqa: F401
    import agents.extraction.agents.symbol_agent   # noqa: F401
    import agents.extraction.agents.text_agent     # noqa: F401
    import agents.extraction.agents.line_agent     # noqa: F401
    loaded = R.assert_no_ml_imported()
    assert loaded == [], f"trained-model packages were imported: {loaded}"


def test_ml_packages_are_not_declared_as_dependencies():
    """A dependency that is never used is still an invitation to use it."""
    for rel in ("requirements.txt", "pyproject.toml"):
        text = (STUDIO / rel).read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip().lstrip('"')
            if stripped.startswith("#") or not stripped:
                continue
            for pkg in ("torch", "torchvision", "ultralytics",
                        "rapidocr-onnxruntime"):
                assert not stripped.startswith(pkg), \
                    f"{rel} still declares {pkg}: {line}"


def test_dockerfile_does_not_install_torch():
    text = (STUDIO.parent / "Dockerfile").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.strip().startswith("#"):
            continue
        assert "torch" not in line, f"Dockerfile still installs torch: {line}"


def test_ultralytics_probe_never_imports_ultralytics():
    """Importing ultralytics pulls in torch, which is the dependency this
    pipeline is meant not to have."""
    from extraction_cli.image import _check_ultralytics
    assert _check_ultralytics() is False
    assert "ultralytics" not in sys.modules


# ── 5. Every call site goes through the router ──────────────────────────────

@pytest.mark.parametrize("relpath", [
    "main.py",
    "api/detect.py",
    "extraction_cli/image.py",
    "agents/extraction/agents/symbol_agent.py",
    "agents/extraction/agents/text_agent.py",
    "agents/extraction/agents/line_agent.py",
])
def test_call_sites_use_the_router(relpath):
    src = (STUDIO / relpath).read_text(encoding="utf-8")
    assert "detection_router" in src, (
        f"{relpath} must resolve its detectors through "
        f"services/detection_router.py, not import one backend directly"
    )


def test_agentic_warmup_does_not_load_trained_models():
    """The warmup node used to call _init_cv_models(), loading YOLOv8,
    RapidOCR and U-Net on every agentic extraction run.

    Checked against the parsed syntax tree, not the raw text: the module's
    docstring legitimately explains that the call was removed, so a substring
    search would match its own explanation.
    """
    import ast
    tree = ast.parse((STUDIO / "agents" / "extraction" / "agents"
                      / "orchestration.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = getattr(fn, "id", None) or getattr(fn, "attr", None)
            assert name != "_init_cv_models",                 "orchestration.py still calls _init_cv_models()"
        if isinstance(node, ast.ImportFrom):
            imported = {a.name for a in node.names}
            assert "_init_cv_models" not in imported,                 "orchestration.py still imports _init_cv_models"


def test_agentic_warmup_fails_fast_without_vision(blind):
    from agents.streaming import FatalAgentError
    from agents.extraction.agents.orchestration import warmup
    with pytest.raises(FatalAgentError):
        warmup({"pid": "p", "hub": "."})


def test_agentic_warmup_passes_with_vision(seeing):
    from agents.extraction.agents.orchestration import warmup
    assert warmup({"pid": "p", "hub": "."}) == {}


def test_main_warmup_hooks_are_inert():
    """They must exist (cv_bootstrap looks them up by name) but must not
    import or load a trained model."""
    import main
    for name in ("initialize_yolo_model", "initialize_ocr",
                 "initialize_unet_model"):
        fn = getattr(main, name, None)
        assert callable(fn), f"main.{name} must exist"
        assert fn() is None, f"main.{name} must be a no-op"
    assert R.assert_no_ml_imported() == []


def test_cv_bootstrap_survives_missing_hooks(monkeypatch):
    import bootstrap.cv_bootstrap as B
    import main
    monkeypatch.setattr(main, "_DETECTION_AVAILABLE", True, raising=False)
    monkeypatch.delattr(main, "initialize_yolo_model", raising=False)
    B._init_cv_models()          # must not raise


def test_no_commented_ml_fallback_remains():
    """Commented-out fallback blocks made the intent ambiguous."""
    for name in ("llm_symbol_detection_service", "llm_text_detection_service",
                 "llm_line_detection_service"):
        src = (STUDIO / "services" / f"{name}.py").read_text(encoding="utf-8")
        assert "Uncomment to restore" not in src, \
            f"{name} still documents how to re-enable an ML fallback"
