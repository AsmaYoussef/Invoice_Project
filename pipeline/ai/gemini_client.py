"""Official Google Gemini client for structured JSON and Vision line cleanup."""

from __future__ import annotations

import json
import os
from typing import Any

DEFAULT_MODEL = "gemini-2.0-flash"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


def get_api_key() -> str | None:
    key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    return key or None


def get_model() -> str:
    return (os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL).strip()


def is_vision_enabled() -> bool:
    if not get_api_key():
        return False
    return _env_bool("GEMINI_VISION_ENABLED", default=True)


def _get_client():
    from google import genai

    api_key = get_api_key()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    return genai.Client(api_key=api_key)


def _extract_json_object(text: str) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            return None
    return None


def ask_structured_json(
    prompt: str,
    *,
    retries: int = 2,
    timeout_s: int = 45,
    max_response_chars: int = 120000,
    system_instruction: str | None = None,
) -> dict:
    """Drop-in replacement for legacy Bard client. Returns {ok, parsed_json, ...}."""
    if not get_api_key():
        return {
            "ok": False,
            "error": "GEMINI_API_KEY not set",
            "response_text": "",
            "parsed_json": None,
            "truncated": False,
            "response_chars": 0,
        }

    last_error = ""
    for attempt in range(retries + 1):
        try:
            client = _get_client()
            from google.genai import types

            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            )
            if system_instruction:
                config.system_instruction = system_instruction

            response = client.models.generate_content(
                model=get_model(),
                contents=prompt,
                config=config,
            )
            response_text = (response.text or "").strip()
            truncated = False
            if len(response_text) > max_response_chars:
                response_text = response_text[:max_response_chars]
                truncated = True
            parsed = _extract_json_object(response_text)
            return {
                "ok": parsed is not None,
                "error": "" if parsed is not None else "json_parse_failed",
                "response_text": response_text,
                "parsed_json": parsed,
                "truncated": truncated,
                "response_chars": len(response_text),
                "attempt": attempt + 1,
            }
        except Exception as exc:
            last_error = str(exc)
    return {
        "ok": False,
        "error": last_error or "unknown_error",
        "response_text": "",
        "parsed_json": None,
        "truncated": False,
        "response_chars": 0,
    }


def generate_vision_json(
    *,
    system_instruction: str,
    user_text: str,
    image_bytes_list: list[bytes],
    mime_type: str = "image/jpeg",
    retries: int = 1,
    timeout_s: int = 60,
) -> dict:
    """Vision + text → parsed JSON dict."""
    if not get_api_key():
        return {"ok": False, "error": "GEMINI_API_KEY not set", "parsed_json": None}

    last_error = ""
    for attempt in range(retries + 1):
        try:
            client = _get_client()
            from google.genai import types

            parts: list[Any] = []
            for img_bytes in image_bytes_list:
                parts.append(
                    types.Part.from_bytes(data=img_bytes, mime_type=mime_type)
                )
            parts.append(types.Part.from_text(text=user_text))

            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                temperature=0.1,
            )

            response = client.models.generate_content(
                model=get_model(),
                contents=parts,
                config=config,
            )
            response_text = (response.text or "").strip()
            parsed = _extract_json_object(response_text)
            return {
                "ok": parsed is not None,
                "error": "" if parsed is not None else "json_parse_failed",
                "response_text": response_text,
                "parsed_json": parsed,
                "attempt": attempt + 1,
            }
        except Exception as exc:
            last_error = str(exc)
    return {"ok": False, "error": last_error or "unknown_error", "parsed_json": None}
