"""LLM client factories — only Qwen 3.8-Max and Gemini 3.6 Flash."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Optional, Type

from pydantic import BaseModel

from agent.config import (
    GEMINI_MODEL,
    GOOGLE_API_KEY,
    QWEN_API_KEY,
    QWEN_BASE_URL,
    QWEN_MODEL,
)


@lru_cache(maxsize=4)
def get_qwen(temperature: float = 0.0) -> Any:
    """Qwen 3.8-Max via OpenAI-compatible API (reasoning / structured output)."""
    if not QWEN_API_KEY:
        raise RuntimeError(
            "QWEN_API_KEY (or OPENAI_API_KEY) is not set. "
            "Configure it in .env to use reasoning model."
        )
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=QWEN_MODEL,
        api_key=QWEN_API_KEY,
        base_url=QWEN_BASE_URL,
        temperature=temperature,
        max_tokens=4096,
    )


@lru_cache(maxsize=4)
def get_gemini(temperature: float = 0.0) -> Any:
    """Gemini 3.6 Flash for fast classification / bulk extraction."""
    if not GOOGLE_API_KEY:
        raise RuntimeError(
            "GOOGLE_API_KEY (or GEMINI_API_KEY) is not set. "
            "Configure it in .env to use Gemini Flash."
        )
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=GEMINI_MODEL,
        google_api_key=GOOGLE_API_KEY,
        temperature=temperature,
    )


def qwen_structured(
    schema: Type[BaseModel],
    *,
    temperature: float = 0.0,
) -> Any:
    """Qwen with Pydantic structured output (Master Plan §5.3)."""
    llm = get_qwen(temperature=temperature)
    return llm.with_structured_output(schema)


def invoke_with_system(
    llm: Any,
    system: str,
    user: str,
    *,
    use_cache_control: bool = True,
) -> Any:
    """Invoke chat model with stable system prompt first (prompt caching ready)."""
    from langchain_core.messages import HumanMessage, SystemMessage

    messages: list[Any] = []
    # Ephemeral cache_control for OpenAI-compatible providers that support it
    if use_cache_control:
        try:
            messages.append(
                SystemMessage(
                    content=[
                        {
                            "type": "text",
                            "text": system,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ]
                )
            )
        except Exception:  # noqa: BLE001
            messages.append(SystemMessage(content=system))
    else:
        messages.append(SystemMessage(content=system))

    messages.append(HumanMessage(content=user))
    return llm.invoke(messages)
