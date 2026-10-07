import pytest

from src.config import AtlasConfig, ConfigError, load_config

_ENV_VARS = (
    "TAVILY_API_KEY",
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "ATLAS_LLM_PROVIDER",
    "ATLAS_MODEL",
    "ATLAS_OLLAMA_BASE_URL",
    "ATLAS_MAX_RESEARCH_ITERATIONS",
    "ATLAS_SEARCH_RESULTS_PER_QUERY",
)


@pytest.fixture
def clean_env(monkeypatch):
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def test_validate_passes_with_only_tavily_key():
    # No OpenAI/Google key is required for the default Ollama provider.
    AtlasConfig(tavily_api_key="b").validate()


def test_validate_requires_tavily_key():
    with pytest.raises(ConfigError) as exc:
        AtlasConfig().validate()
    assert "TAVILY_API_KEY" in str(exc.value)


def test_validate_rejects_unknown_provider():
    with pytest.raises(ConfigError) as exc:
        AtlasConfig(tavily_api_key="b", llm_provider="openai").validate()
    assert "ATLAS_LLM_PROVIDER" in str(exc.value)


def test_load_config_ollama_defaults(clean_env):
    cfg = load_config(dotenv_path="nonexistent.env")
    assert cfg.llm_provider == "ollama"
    assert cfg.model == "qwen3:4b"
    assert cfg.ollama_base_url == "http://127.0.0.1:11434"
    assert cfg.max_research_iterations == 3
    assert cfg.search_results_per_query == 5


def test_load_config_reads_env(clean_env):
    clean_env.setenv("ATLAS_MODEL", "qwen3:4b")
    clean_env.setenv("ATLAS_OLLAMA_BASE_URL", "http://192.168.1.5:11434/")
    clean_env.setenv("ATLAS_MAX_RESEARCH_ITERATIONS", "7")
    cfg = load_config(dotenv_path="nonexistent.env")
    assert cfg.model == "qwen3:4b"
    assert cfg.ollama_base_url == "http://192.168.1.5:11434"  # trailing slash stripped
    assert cfg.max_research_iterations == 7


def test_load_config_rejects_bad_int(clean_env):
    clean_env.setenv("ATLAS_MAX_RESEARCH_ITERATIONS", "many")
    with pytest.raises(ConfigError):
        load_config(dotenv_path="nonexistent.env")


def test_load_config_rejects_zero_iterations(clean_env):
    clean_env.setenv("ATLAS_MAX_RESEARCH_ITERATIONS", "0")
    with pytest.raises(ConfigError):
        load_config(dotenv_path="nonexistent.env")
