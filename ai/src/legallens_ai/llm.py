"""Builds the Claude clients and turns Anthropic SDK errors into the layer's typed errors.

One place decides how every model is configured, so the router, rewriter and the three
workflows behave the same on a missing key, an outage or an unknown model id.
"""

import logging

import anthropic
from langchain_anthropic import ChatAnthropic
from pydantic import SecretStr

from legallens_ai.config import AISettings, Effort
from legallens_ai.errors import (
    ModelConfigurationError,
    ModelUnavailableError,
    OrchestratorError,
)

# Models that accept the server-side refusal fallback (`fallbacks: "default"`).
FALLBACK_MODELS = frozenset({"claude-sonnet-5-5", "claude-opus-5-5", "claude-opus-5"})
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def require_api_key(settings: AISettings) -> SecretStr:
    key = settings.anthropic_api_key
    if key is None or not key.get_secret_value():
        raise ModelConfigurationError(
            "model_auth_missing",
            "ANTHROPIC_API_KEY is not set. Add it to ai/.env or the environment.",
        )
    return key


def generation_model(
    settings: AISettings,
    *,
    model: str,
    effort: Effort,
    max_tokens: int,
    timeout_s: float,
) -> ChatAnthropic:
    """A streaming-ready Sonnet / Opus client: adaptive thinking at the given effort.

    Thinking can't be switched off on Sonnet 5.5 / Opus 5.5; effort is the control. The
    thinking text isn't requested (display defaults to omitted) and is never shown.
    """
    extra: dict[str, object] = {}
    betas: list[str] | None = None
    if settings.refusal_fallbacks and model in FALLBACK_MODELS:
        betas = [FALLBACK_BETA]
        extra["fallbacks"] = "default"
    return ChatAnthropic(
        model=model,
        api_key=require_api_key(settings),
        max_tokens=max_tokens,
        timeout=timeout_s,
        max_retries=settings.generation_max_retries,
        thinking={"type": "adaptive"},
        effort=effort,
        betas=betas,
        model_kwargs=extra,
    )


def map_anthropic_error(
    exc: anthropic.APIError, *, log: logging.Logger, event: str, model_setting: str
) -> OrchestratorError:
    """The typed error for an SDK failure. ``event`` prefixes the log line (metadata only)."""
    if isinstance(exc, anthropic.AuthenticationError | anthropic.PermissionDeniedError):
        log.warning("%s_auth_failed status=%s", event, exc.status_code)
        return ModelConfigurationError(
            "model_auth_failed", "The Anthropic API key was rejected. Check ANTHROPIC_API_KEY."
        )
    if isinstance(exc, anthropic.APIConnectionError | anthropic.RateLimitError):
        log.warning("%s_unavailable error=%s", event, type(exc).__name__)
        return ModelUnavailableError()
    if isinstance(exc, anthropic.APIStatusError):
        log.warning("%s_error status=%s", event, exc.status_code)
        if exc.status_code >= 500:  # includes 529 overloaded
            return ModelUnavailableError()
        return ModelConfigurationError(
            "model_request_failed",
            f"The model rejected the request ({exc.status_code}). Check {model_setting}.",
        )
    log.warning("%s_error error=%s", event, type(exc).__name__)
    return ModelUnavailableError()
