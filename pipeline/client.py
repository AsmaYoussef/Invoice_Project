"""Gemini client shim — delegates to official google-genai SDK."""

try:
    from pipeline.ai.gemini_client import (  # noqa: F401
        ask_structured_json,
        generate_vision_json,
        get_api_key,
        get_model,
        is_vision_enabled,
    )
except ImportError:
    from ai.gemini_client import (  # noqa: F401
        ask_structured_json,
        generate_vision_json,
        get_api_key,
        get_model,
        is_vision_enabled,
    )

__all__ = [
    "ask_structured_json",
    "generate_vision_json",
    "get_api_key",
    "get_model",
    "is_vision_enabled",
]
