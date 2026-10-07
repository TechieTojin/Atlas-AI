"""Ollama preflight and LLM factory tests — no live Ollama server needed."""

import pytest

from src.config import AtlasConfig, ConfigError
from src.llm import OllamaNotAvailableError, check_ollama, create_llm, preflight


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _get_with(payload):
    def http_get(url):
        return FakeResponse(payload)

    return http_get


class TestCheckOllama:
    def test_passes_when_model_installed(self):
        http_get = _get_with({"models": [{"name": "qwen3:8b"}, {"name": "llama3:8b"}]})
        check_ollama("http://127.0.0.1:11434", "qwen3:8b", http_get=http_get)

    def test_bare_model_name_matches_any_tag(self):
        http_get = _get_with({"models": [{"name": "qwen3:8b"}]})
        check_ollama("http://127.0.0.1:11434", "qwen3", http_get=http_get)

    def test_server_unreachable_gives_friendly_error(self):
        def http_get(url):
            raise ConnectionError("refused")

        with pytest.raises(OllamaNotAvailableError) as exc:
            check_ollama("http://127.0.0.1:11434", "qwen3:8b", http_get=http_get)
        assert "not reachable" in str(exc.value)
        assert "ollama serve" in str(exc.value)

    def test_missing_model_suggests_pull(self):
        http_get = _get_with({"models": [{"name": "llama3:8b"}]})
        with pytest.raises(OllamaNotAvailableError) as exc:
            check_ollama("http://127.0.0.1:11434", "qwen3:8b", http_get=http_get)
        assert "ollama pull qwen3:8b" in str(exc.value)

    def test_malformed_payload_treated_as_missing_model(self):
        http_get = _get_with({"unexpected": True})
        with pytest.raises(OllamaNotAvailableError):
            check_ollama("http://127.0.0.1:11434", "qwen3:8b", http_get=http_get)

    def test_preflight_error_is_config_error(self):
        # main.py catches ConfigError for friendly CLI output, no traceback.
        assert issubclass(OllamaNotAvailableError, ConfigError)


class TestCreateLlm:
    def test_rejects_non_ollama_provider(self):
        with pytest.raises(ConfigError):
            create_llm(AtlasConfig(tavily_api_key="k", llm_provider="openai"))

    def test_creates_chat_ollama_with_config(self):
        cfg = AtlasConfig(
            tavily_api_key="k",
            model="qwen3:8b",
            ollama_base_url="http://127.0.0.1:11434",
        )
        llm = create_llm(cfg)  # constructing ChatOllama makes no network call
        assert llm.model == "qwen3:8b"
        assert llm.base_url == "http://127.0.0.1:11434"
        assert llm.reasoning is False  # thinking off by default (synthesis)

    def test_reasoning_enabled_for_structured_calls(self):
        # Live-run regression: with reasoning off, qwen3 returned critic
        # score 0 alongside SYNTHESIZE; structured calls enable reasoning.
        cfg = AtlasConfig(tavily_api_key="k")
        assert cfg.ollama_structured_reasoning is True
        llm = create_llm(cfg, reasoning=cfg.ollama_structured_reasoning)
        assert llm.reasoning is True

    def test_preflight_skipped_for_unknown_provider(self):
        # preflight only checks Ollama; other providers fail earlier in validate().
        preflight(AtlasConfig(tavily_api_key="k", llm_provider="other"))
