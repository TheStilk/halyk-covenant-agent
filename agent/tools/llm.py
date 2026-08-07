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

import agent.config as _cfg

T = TypeVar("T", bound=BaseModel)


def is_llm_available() -> bool:
    """True when primary chat LLM is fully configured (reads live config)."""
    return bool(_cfg.LLM_API_KEY and _cfg.LLM_BASE_URL and _cfg.LLM_MODEL)


def llm_status_message() -> str:
    missing = []
    if not _cfg.LLM_API_KEY:
        missing.append("LLM_API_KEY")
    if not _cfg.LLM_BASE_URL:
        missing.append("LLM_BASE_URL")
    if not _cfg.LLM_MODEL:
        missing.append("LLM_MODEL")
    if missing:
        return f"LLM unavailable: set {', '.join(missing)} in env"
    return f"LLM available: model={_cfg.LLM_MODEL} base={_cfg.LLM_BASE_URL}"


def _make_chat(
    *,
    api_key: str,
    base_url: str,
    model: str,
    temperature: float,
) -> Any:
    from langchain_openai import ChatOpenAI

    # Floor 512 so env LLM_MAX_TOKENS=500 still works; default config is 1024
    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
        "temperature": temperature,
        "max_tokens": max(512, int(getattr(_cfg, "LLM_MAX_TOKENS", 1024))),
    }
    try:
        return ChatOpenAI(
            **kwargs,
            timeout=_cfg.LLM_TIMEOUT_SEC,
            max_retries=max(0, _cfg.LLM_MAX_RETRIES),
        )
    except TypeError:
        return ChatOpenAI(**kwargs)


@lru_cache(maxsize=16)
def get_chat_model(temperature: float = 0.0) -> Any:
    """Primary OpenAI-compatible chat model from live LLM_* config."""
    if not is_llm_available():
        raise RuntimeError(llm_status_message())
    # Cache key includes key fingerprint so hot-swap works after cache_clear
    return _make_chat(
        api_key=_cfg.LLM_API_KEY,
        base_url=_cfg.LLM_BASE_URL,
        model=_cfg.LLM_MODEL,
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
    if _cfg.CLASSIFY_API_KEY and _cfg.CLASSIFY_BASE_URL and _cfg.CLASSIFY_MODEL:
        return True
    return is_llm_available()


@lru_cache(maxsize=16)
def get_classify_model(temperature: float = 0.0) -> Any:
    """Model for optional PDF classify (OpenAI-compatible).

    Prefer CLASSIFY_* if set; else primary LLM_*.
    """
    if _cfg.CLASSIFY_API_KEY and _cfg.CLASSIFY_BASE_URL and _cfg.CLASSIFY_MODEL:
        return _make_chat(
            api_key=_cfg.CLASSIFY_API_KEY,
            base_url=_cfg.CLASSIFY_BASE_URL,
            model=_cfg.CLASSIFY_MODEL,
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


def _is_rate_limit_error(exc: BaseException) -> bool:
    msg = f"{type(exc).__name__} {exc}".lower().replace("-", "").replace("_", "")
    return (
        "429" in msg
        or "ratelimit" in msg
        or "toomanyrequests" in msg
        or "resourceexhausted" in msg
        or "quotaexceeded" in msg
    )


def _retry_sleep(attempt: int, exc: BaseException) -> None:
    """Backoff: longer on 429 (2s, 4s, 8s…), short otherwise (0.5s, 1s…)."""
    if _is_rate_limit_error(exc):
        delay = min(30.0, 2.0 * (2**attempt))
    else:
        delay = 0.5 * (attempt + 1)
    time.sleep(delay)


def structured_invoke(
    schema: Type[T],
    *,
    system: str,
    user: str,
    temperature: float = 0.0,
    max_retries: Optional[int] = None,
) -> T:
    """Invoke structured output with simple retry + rate-limit backoff."""
    if not is_llm_available():
        raise RuntimeError(llm_status_message())

    from langchain_core.messages import HumanMessage, SystemMessage

    retries = _cfg.LLM_MAX_RETRIES if max_retries is None else max_retries
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
                _retry_sleep(attempt, exc)
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
