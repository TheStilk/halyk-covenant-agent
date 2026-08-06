"""Provider-agnostic OpenAI-compatible LLM client.

Configure via env only (no business-logic hardcoding of vendor):

  LLM_API_KEY=...
  LLM_BASE_URL=https://openrouter.ai/api/v1   # or any OpenAI-compatible /v1
  LLM_MODEL=qwen/qwen3.5-max

Aliases: QWEN_* / OPENAI_* still work (see agent.config).
"""

from __future__ import annotations

import time
from functools import lru_cache
from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel

from agent.config import (
    GEMINI_MODEL,
    GOOGLE_API_KEY,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MAX_RETRIES,
    LLM_MODEL,
    LLM_TIMEOUT_SEC,
)

T = TypeVar("T", bound=BaseModel)


def is_llm_available() -> bool:
    """True when API key + base URL + model are configured."""
    return bool(LLM_API_KEY and LLM_BASE_URL and LLM_MODEL)


def llm_status_message() -> str:
    if not LLM_API_KEY:
        return "LLM unavailable: LLM_API_KEY (or QWEN_API_KEY/OPENAI_API_KEY) not set"
    if not LLM_BASE_URL:
        return "LLM unavailable: LLM_BASE_URL not set"
    if not LLM_MODEL:
        return "LLM unavailable: LLM_MODEL not set"
    return f"LLM available: model={LLM_MODEL} base={LLM_BASE_URL}"


@lru_cache(maxsize=8)
def get_chat_model(temperature: float = 0.0) -> Any:
    """OpenAI-compatible chat model (ChatOpenAI) for any provider behind base_url."""
    if not is_llm_available():
        raise RuntimeError(llm_status_message())
    from langchain_openai import ChatOpenAI

    # request_timeout / max_retries depend on langchain_openai version
    kwargs: dict[str, Any] = {
        "model": LLM_MODEL,
        "api_key": LLM_API_KEY,
        "base_url": LLM_BASE_URL,
        "temperature": temperature,
        "max_tokens": 4096,
    }
    try:
        return ChatOpenAI(
            **kwargs,
            timeout=LLM_TIMEOUT_SEC,
            max_retries=max(0, LLM_MAX_RETRIES),
        )
    except TypeError:
        return ChatOpenAI(**kwargs)


def get_qwen(temperature: float = 0.0) -> Any:
    """Backward-compatible alias → provider-agnostic chat model."""
    return get_chat_model(temperature=temperature)


@lru_cache(maxsize=4)
def get_gemini(temperature: float = 0.0) -> Any:
    """Optional Gemini Flash for doc classify only (separate from formula LLM)."""
    if not GOOGLE_API_KEY:
        raise RuntimeError(
            "GOOGLE_API_KEY (or GEMINI_API_KEY) is not set. "
            "Optional — not required for formula reader."
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
    """Structured output runner (any OpenAI-compatible model)."""
    llm = get_chat_model(temperature=temperature)
    return llm.with_structured_output(schema)


def structured_invoke(
    schema: Type[T],
    *,
    system: str,
    user: str,
    temperature: float = 0.0,
    max_retries: Optional[int] = None,
) -> T:
    """Invoke structured output with simple retry. Raises if LLM unavailable or all retries fail."""
    if not is_llm_available():
        raise RuntimeError(llm_status_message())

    from langchain_core.messages import HumanMessage, SystemMessage

    retries = LLM_MAX_RETRIES if max_retries is None else max_retries
    last_exc: Optional[BaseException] = None
    for attempt in range(retries + 1):
        try:
            llm = get_chat_model(temperature=temperature)
            structured = llm.with_structured_output(schema)
            result = structured.invoke(
                [SystemMessage(content=system), HumanMessage(content=user)]
            )
            if isinstance(result, schema):
                return result
            return schema.model_validate(result)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            break
    assert last_exc is not None
    raise last_exc


def invoke_json_text(
    *,
    system: str,
    user: str,
    temperature: float = 0.0,
) -> str:
    """Plain text invoke (for smoke / free-form JSON parse fallback)."""
    if not is_llm_available():
        raise RuntimeError(llm_status_message())
    llm = get_chat_model(temperature=temperature)
    raw = invoke_with_system(llm, system, user, use_cache_control=False)
    return raw.content if hasattr(raw, "content") else str(raw)


def invoke_with_system(
    llm: Any,
    system: str,
    user: str,
    *,
    use_cache_control: bool = True,
) -> Any:
    """Invoke chat model with stable system prompt first."""
    from langchain_core.messages import HumanMessage, SystemMessage

    messages: list[Any] = []
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
