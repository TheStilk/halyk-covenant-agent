# Pydantic V2 & LangChain LLM Error Recovery Research

When using LangChain's `llm.with_structured_output()` with strict Pydantic models, a common issue is that the LLM might omit a required field (such as `status`), resulting in a `ValidationError` that crashes the execution and discards the LLM's response. 

Here is a summary of strategies to handle partial or malformed LLM outputs based on official LangChain and Pydantic V2 documentation.

## 1. LangChain Native Error Handling

LangChain's `with_structured_output` method has built-in parameters to gracefully manage parsing failures:

*   **`include_raw=True`**: Instead of crashing on validation, this returns a dictionary containing `raw` (the raw LLM output), `parsed` (the parsed model, if successful), and `parsing_error` (the `ValidationError` if it failed). This allows you to log the raw output and apply manual recovery logic.
*   **`handle_errors=True`** (or passing a string/callable): Tells LangChain to catch the `ValidationError` internally. If set to `True`, it returns a generic error message string. You can also pass a custom function `Callable[[Exception], str]` to intercept the error and return a specific message back to the pipeline.

## 2. OutputFixingParser & RetryOutputParser

If you want the LLM to automatically fix its own mistakes, LangChain provides output parsers designed for error recovery. **Note**: These were primarily designed for text-based parsing rather than native tool-calling, but they can be used in a custom fallback chain if `with_structured_output` fails.

*   **`OutputFixingParser`**: Wraps a standard parser and a secondary LLM call. If a `ValidationError` occurs, it sends the malformed output and the error message to the LLM and asks it to correct the formatting.
*   **`RetryOutputParser`**: Similar to the fixing parser but also passes the **original prompt** to the LLM. This is useful when the LLM needs context from the original request to correctly populate the missing fields (e.g., if it hallucinated or forgot the `status` requested in the prompt).

## 3. Pydantic V2 Resiliency Techniques

Instead of relying on LLM retries (which cost extra tokens and latency), you can make the Pydantic schema itself resilient to partial outputs.

### A. Optional Fields and `default_factory`
Make frequently omitted fields optional by using `Optional[Type] = None` or providing a default value. In Pydantic V2.10+, `default_factory` can even accept the already validated data to derive a default based on other fields. You can then apply business logic later to check if the field needs to be filled.

### B. `@model_validator(mode='before')` (Recommended)
The most robust Pydantic V2 pattern for LLM recovery is using a `model_validator` with `mode='before'`. This intercepts the raw dictionary output from the LLM **before** Pydantic attempts strict validation. 

```python
from typing import Any
from pydantic import BaseModel, model_validator

class AgentResponse(BaseModel):
    summary: str
    status: str

    @model_validator(mode='before')
    @classmethod
    def inject_missing_status(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # If the LLM omitted the required 'status' field, inject a default or fallback
            if "status" not in data or not data.get("status"):
                data["status"] = "unknown"
        return data
```
Using `mode='before'` ensures you avoid the `ValidationError` entirely, allowing the chain to continue successfully even if the LLM provided partial data. `field_validator` or `mode='after'` validators are less helpful for missing fields, as Pydantic will raise an error before those validators run.

## Sources
* [LangChain Documentation: Structured Output & Error Handling](https://python.langchain.com/v0.2/docs/how_to/structured_output/)
* [LangChain Documentation: Output Parsers (Retry/Fixing)](https://python.langchain.com/v0.1/docs/modules/model_io/output_parsers/types/retry/)
* [Pydantic V2 Documentation: Validators (`model_validator`)](https://docs.pydantic.dev/latest/concepts/validators/)
