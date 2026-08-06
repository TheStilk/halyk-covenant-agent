"""Provider-agnostic OpenAI-compatible LLM client.

Swap provider/model via env only:

  LLM_API_KEY=...
  LLM_BASE_URL=https://host/v1
  LLM_MODEL=any-model-id

No vendor-specific roles in business logic.
"""

from __future__ import annotations

import time
from functools import lru_cache
from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel

from agent.config import (
    CLASSIFY_API_KEY,
    CLASSIFY_BASE_URL,
    CLASSIFY_MODEL,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MAX_RETRIES,
    LLM_MODEL,
    LLM_TIMEOUT_SEC,
)

T = TypeVar("T", bound=BaseModel)


def is_llm_available() -> bool:
    """True when primary chat LLM is fully configured."""
    return bool(LLM_API_KEY and LLM_BASE_URL and LLM_MODEL)


def llm_status_message() -> str:
    missing = []
    if not LLM_API_KEY:
        missing.append("LLM_API_KEY")
    if not LLM_BASE_URL:
        missing.append("LLM_BASE_URL")
    if not LLM_MODEL:
        missing.append("LLM_MODEL")
    if missing:
        return f"LLM unavailable: set {', '.join(missing)} in env"
    return f"LLM available: model={LLM_MODEL} base={LLM_BASE_URL}"


def _make_chat(
    *,
    api_key: str,
    base_url: str,
    model: str,
    temperature: float,
) -> Any:
    from langchain_openai import ChatOpenAI

    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
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


@lru_cache(maxsize=8)
def get_chat_model(temperature: float = 0.0) -> Any:
    """Primary OpenAI-compatible chat model from LLM_* env."""
    if not is_llm_available():
        raise RuntimeError(llm_status_message())
    return _make_chat(
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        model=LLM_MODEL,
        temperature=temperature,
    )


def get_llm(temperature: float = 0.0) -> Any:
    """Alias for get_chat_model (preferred name in call sites)."""
    return get_chat_model(temperature=temperature)


# Backward-compatible name — same as get_llm
def get_qwen(temperature: float = 0.0) -> Any:
    return get_chat_model(temperature=temperature)


def is_classify_llm_available() -> bool:
    """Classify LLM: dedicated CLASSIFY_* or fallback to primary LLM_*."""
    if CLASSIFY_API_KEY and CLASSIFY_BASE_URL and CLASSIFY_MODEL:
        # If only Google key is set without OpenAI-compatible base, not usable here
        if CLASSIFY_BASE_URL:
            return True
    return is_llm_available()


@lru_cache(maxsize=8)
def get_classify_model(temperature: float = 0.0) -> Any:
    """Model for optional PDF classify (OpenAI-compatible).

    Prefer CLASSIFY_* if set; else primary LLM_*.
    """
    if CLASSIFY_API_KEY and CLASSIFY_BASE_URL and CLASSIFY_MODEL:
        return _make_chat(
            api_key=CLASSIFY_API_KEY,
            base_url=CLASSIFY_BASE_URL,
            model=CLASSIFY_MODEL,
            temperature=temperature,
        )
    return get_chat_model(temperature=temperature)


def get_gemini(temperature: float = 0.0) -> Any:
    """Deprecated alias → get_classify_model (OpenAI-compatible only)."""
    return get_classify_model(temperature=temperature)


def llm_structured(
    schema: Type[BaseModel],
    *,
    temperature: float = 0.0,
) -> Any:
    llm = get_chat_model(temperature=temperature)
    return llm.with_structured_output(schema)


def qwen_structured(
    schema: Type[BaseModel],
    *,
    temperature: float = 0.0,
) -> Any:
    """Deprecated alias → llm_structured."""
    return llm_structured(schema, temperature=temperature)


def structured_invoke(
    schema: Type[T],
    *,
    system: str,
    user: str,
    temperature: float = 0.0,
    max_retries: Optional[int] = None,
) -> T:
    """Invoke structured output with simple retry."""
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
