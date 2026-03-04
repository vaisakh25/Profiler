"""Configurable LLM factory for the profiling agent.

Reads ``LLM_PROVIDER`` and ``LLM_MODEL`` from the environment.
Supported providers:

* ``anthropic`` (default) — requires ``langchain-anthropic`` + ``ANTHROPIC_API_KEY``
* ``openai``              — requires ``langchain-openai``    + ``OPENAI_API_KEY``
* ``google``              — requires ``langchain-google-genai`` + ``GOOGLE_API_KEY``
"""

from __future__ import annotations

import os
from typing import Optional

from langchain_core.language_models.chat_models import BaseChatModel

# Default models per provider
_DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-4-20250514",
    "openai": "gpt-4o",
    "google": "gemini-2.0-flash",
}


def get_llm(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.0,
) -> BaseChatModel:
    """Create a chat model instance.

    Args:
        provider: One of ``"anthropic"``, ``"openai"``, ``"google"``.
                  Falls back to the ``LLM_PROVIDER`` env var, then ``"anthropic"``.
        model:    Model name override.  Falls back to ``LLM_MODEL`` env var,
                  then a sensible default per provider.
        temperature: Sampling temperature (default 0 for deterministic profiling).

    Returns:
        A LangChain ``BaseChatModel`` instance ready for ``.bind_tools()``.

    Raises:
        ImportError: If the required provider package is not installed.
        ValueError:  If the provider name is not recognised.
    """
    provider = (provider or os.getenv("LLM_PROVIDER", "anthropic")).lower()
    model = model or os.getenv("LLM_MODEL") or _DEFAULT_MODELS.get(provider)

    if provider == "anthropic":
        return _make_anthropic(model, temperature)
    if provider == "openai":
        return _make_openai(model, temperature)
    if provider == "google":
        return _make_google(model, temperature)

    raise ValueError(
        f"Unknown LLM provider '{provider}'. "
        f"Supported: anthropic, openai, google."
    )


def _make_anthropic(model: str, temperature: float) -> BaseChatModel:
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError as exc:
        raise ImportError(
            "langchain-anthropic is required for the Anthropic provider. "
            "Install it with: pip install langchain-anthropic"
        ) from exc
    return ChatAnthropic(model=model, temperature=temperature)


def _make_openai(model: str, temperature: float) -> BaseChatModel:
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise ImportError(
            "langchain-openai is required for the OpenAI provider. "
            "Install it with: pip install langchain-openai"
        ) from exc
    return ChatOpenAI(model=model, temperature=temperature)


def _make_google(model: str, temperature: float) -> BaseChatModel:
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as exc:
        raise ImportError(
            "langchain-google-genai is required for the Google provider. "
            "Install it with: pip install langchain-google-genai"
        ) from exc
    return ChatGoogleGenerativeAI(model=model, temperature=temperature)
