"""Tests for LLM model configuration helpers."""

from __future__ import annotations

import litellm
import pytest
from agents.extensions.models.litellm_model import LitellmModel
from agents.model_settings import ModelSettings
from agents.models import _openai_shared
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from agents.models.openai_responses import OpenAIResponsesModel

from strix.config import models
from strix.config.models import (
    StrixProvider,
    _NonStreamingModel,
    _TurnGuardModel,
    configure_sdk_model_defaults,
    request_timeout_extra_args,
    resolve_api_type,
    routes_through_litellm,
    supports_strict_tool_schemas,
    uses_chat_completions_tool_schema,
)
from strix.config.settings import Settings
from strix.llm.request_log import RequestLoggingModel


def test_request_timeout_extra_args_positive() -> None:
    assert request_timeout_extra_args(300) == {"timeout": 300}
    assert request_timeout_extra_args(10) == {"timeout": 10}


def test_request_timeout_extra_args_survives_model_settings_json_dump() -> None:
    """The Chat Completions and LiteLLM paths pydantic-serialize ModelSettings for
    their tracing span; a non-JSON-serializable timeout fails every turn there."""
    settings = ModelSettings(extra_args=request_timeout_extra_args(300))
    assert settings.to_json_dict()["extra_args"] == {"timeout": 300}


@pytest.mark.parametrize("value", [None, 0, -1])
def test_request_timeout_extra_args_disabled(value: float | None) -> None:
    assert request_timeout_extra_args(value) is None


@pytest.mark.parametrize(
    "model_name",
    [
        "anthropic/claude-sonnet-4-6",
        "bedrock/anthropic.claude-opus-4-8-v1:0",
        "vertex_ai/claude-sonnet-5",
        "Sonnet-5",
    ],
)
def test_claude_routes_reject_strict_tool_schemas(model_name: str) -> None:
    assert not supports_strict_tool_schemas(model_name)


@pytest.mark.parametrize(
    "model_name",
    ["openai/gpt-5.4", "gpt-5.4", "gemini/gemini-3.1-pro-preview", "deepseek/deepseek-v4"],
)
def test_other_routes_keep_strict_tool_schemas(model_name: str) -> None:
    assert supports_strict_tool_schemas(model_name)


@pytest.mark.parametrize(
    ("model_name", "litellm"),
    [
        ("claude-sonnet-4-5", False),
        ("openai/claude-sonnet-4-5", False),
        ("any-llm/anthropic/claude-sonnet-4-5", False),
        ("anthropic/claude-sonnet-4-5", True),
        ("litellm/anthropic/claude-sonnet-4-5", True),
        ("bedrock/anthropic.claude-sonnet-4-5-20250929-v1:0", True),
        ("ollama/llama3", True),
    ],
)
def test_routes_through_litellm_matches_the_provider(
    monkeypatch: pytest.MonkeyPatch, model_name: str, litellm: bool
) -> None:
    """The helper must agree with what StrixProvider actually builds.

    Callers use it to decide whether a LiteLLM-only request field is safe to
    attach; on the SDK's own clients such a field raises TypeError mid-turn, so
    drift here breaks every request on that route.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    assert routes_through_litellm(model_name) is litellm
    try:
        model = StrixProvider().get_model(model_name)
    except ImportError:
        # any-llm's client is an optional dependency; reaching it at all already
        # proves the route is not LiteLLM's.
        assert not litellm
        return
    while isinstance(model, _NonStreamingModel | _TurnGuardModel | RequestLoggingModel):
        model = model._inner
    assert isinstance(model, LitellmModel) is litellm


def test_api_type_override_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRIX_LLM", "gpt-4")
    monkeypatch.setenv("STRIX_API_TYPE", "chat_completions")
    assert uses_chat_completions_tool_schema("gpt-4", Settings()) is True
    monkeypatch.setenv("STRIX_LLM", "openai/gpt-4")
    monkeypatch.setenv("STRIX_API_TYPE", "responses")
    assert uses_chat_completions_tool_schema("openai/gpt-4", Settings()) is False
    monkeypatch.setenv("STRIX_LLM", "anthropic/claude-sonnet-4-5")
    assert uses_chat_completions_tool_schema("anthropic/claude-sonnet-4-5", Settings()) is True


@pytest.mark.parametrize(
    ("api_type", "expected"),
    [
        (None, OpenAIChatCompletionsModel),
        ("chat_completions", OpenAIChatCompletionsModel),
        ("responses", OpenAIResponsesModel),
    ],
)
def test_api_type_overrides_the_api_base_route(
    monkeypatch: pytest.MonkeyPatch, api_type: str | None, expected: type
) -> None:
    """``LLM_API_BASE`` defaults to chat completions. ``STRIX_API_TYPE`` must win."""
    monkeypatch.setattr(_openai_shared, "_use_responses_by_default", True)
    monkeypatch.setattr(_openai_shared, "_default_openai_client", None)
    monkeypatch.setattr(_openai_shared, "_default_openai_key", None)
    monkeypatch.setattr(litellm, "api_key", None)
    monkeypatch.setattr(litellm, "api_base", None)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "")
    monkeypatch.setenv("STRIX_LLM", "gpt-5")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_API_BASE", "https://gateway.example/v1")
    monkeypatch.delenv("STRIX_API_TYPE", raising=False)
    if api_type is not None:
        monkeypatch.setenv("STRIX_API_TYPE", api_type)
    configure_sdk_model_defaults(Settings())
    model = StrixProvider().get_model("gpt-5")
    while isinstance(model, _NonStreamingModel | _TurnGuardModel | RequestLoggingModel):
        model = model._inner
    assert isinstance(model, expected)


def _settings(monkeypatch: pytest.MonkeyPatch, model: str, api_base: str | None) -> Settings:
    monkeypatch.setenv("STRIX_LLM", model)
    monkeypatch.delenv("STRIX_API_TYPE", raising=False)
    for name in ("LLM_API_BASE", "OPENAI_API_BASE", "OPENAI_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    if api_base is not None:
        monkeypatch.setenv("LLM_API_BASE", api_base)
    return Settings()


def test_resolve_api_type_without_base_url_is_responses(monkeypatch: pytest.MonkeyPatch) -> None:
    assert resolve_api_type("gpt-5", _settings(monkeypatch, "gpt-5", None)) == "responses"
    assert resolve_api_type("gpt-4o", _settings(monkeypatch, "gpt-4o", None)) == "responses"


def test_resolve_api_type_gateway_defaults_to_chat_completions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(monkeypatch, "gpt-5.6-sol", "https://gateway.example/v1")
    assert resolve_api_type("gpt-5.6-sol", settings) == "chat_completions"
    assert resolve_api_type("my-private-model", settings) == "chat_completions"


def test_resolve_api_type_responses_only_model_ignores_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model LiteLLM lists on /v1/responses alone cannot be served by chat completions."""
    settings = _settings(monkeypatch, "gpt-daybreak-blue-latest", "https://gateway.example/v1")
    assert resolve_api_type("gpt-daybreak-blue-latest", settings) == "responses"
    assert resolve_api_type("openai/gpt-daybreak-blue-latest", settings) == "responses"
    assert uses_chat_completions_tool_schema("gpt-daybreak-blue-latest", settings) is False


def test_resolve_api_type_openai_host_behind_base_url_is_responses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(monkeypatch, "gpt-5", "https://api.openai.com/v1")
    assert resolve_api_type("gpt-5", settings) == "responses"
    assert uses_chat_completions_tool_schema("gpt-5", settings) is False


def test_resolve_api_type_explicit_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch, "gpt-daybreak-blue-latest", "https://gateway.example/v1")
    monkeypatch.setenv("STRIX_API_TYPE", "chat_completions")
    assert resolve_api_type("gpt-daybreak-blue-latest", Settings()) == "chat_completions"
    monkeypatch.setenv("STRIX_API_TYPE", "Responses")
    assert resolve_api_type("gpt-5", Settings()) == "responses"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("None", "none"), ("HIGH", "high"), (" xhigh ", "xhigh"), ("Max", "max")],
)
def test_reasoning_effort_is_case_insensitive(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: str
) -> None:
    monkeypatch.setenv("STRIX_REASONING_EFFORT", raw)
    monkeypatch.setenv("STRIX_DEDUPE_REASONING_EFFORT", raw)
    settings = Settings()
    assert settings.llm.reasoning_effort == expected
    assert settings.dedupe.reasoning_effort == expected


def test_configure_sdk_api_route_follows_the_given_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``model=`` override picks its own route, not ``STRIX_LLM``'s."""
    routes: list[str] = []
    monkeypatch.setattr(models, "set_default_openai_api", routes.append)
    settings = _settings(monkeypatch, "gpt-5", "https://gateway.example/v1")

    models.configure_sdk_api_route("gpt-5", settings)
    models.configure_sdk_api_route("gpt-daybreak-blue-latest", settings)

    assert routes == ["chat_completions", "responses"]
