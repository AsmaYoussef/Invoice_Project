import requests
import json
import urllib.parse
from typing import Any

URL = "https://gemini.google.com/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate"

HEADERS = {
    "accept": "*/*",
    "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
    "x-same-domain": "1",
    "cookie": ""  # waywaaa
}


def build_payload(prompt):
    inner = [
        [prompt, 0, None, None, None, None, 0],
        ["en-US"],
        ["", "", "", None, None, None, None, None, None, ""],
        "", "", None, [0], 1, None, None, 1, 0,
        None, None, None, None, None, [[0]], 0
    ]

    outer = [None, json.dumps(inner)]

    return urllib.parse.urlencode({
        "f.req": json.dumps(outer)
    }) + "&"


def parse_response(text):
    text = text.replace(")]}'", "")
    best = ""

    for line in text.splitlines():
        if "wrb.fr" not in line:
            continue

        try:
            data = json.loads(line)
        except:
            continue

        entries = []
        if isinstance(data, list):
            if data[0] == "wrb.fr":
                entries = [data]
            else:
                entries = [i for i in data if isinstance(i, list) and i[0] == "wrb.fr"]

        for entry in entries:
            try:
                inner = json.loads(entry[2])

                if isinstance(inner, list) and isinstance(inner[4], list):
                    for c in inner[4]:
                        if isinstance(c, list) and isinstance(c[1], list):
                            txt = "".join([t for t in c[1] if isinstance(t, str)])
                            if len(txt) > len(best):
                                best = txt
            except:
                continue

    return best.strip()


def ask(prompt: str, timeout_s: int = 45) -> str:
    payload = build_payload(prompt)
    res = requests.post(URL, headers=HEADERS, data=payload, timeout=timeout_s)
    if res.status_code != 200:
        return f"[ERROR {res.status_code}]"
    return parse_response(res.text) or "[No response]"


def ask_with_meta(prompt: str, retries: int = 2, timeout_s: int = 45) -> dict:
    last_error = ""
    for attempt in range(retries + 1):
        try:
            text = ask(prompt, timeout_s=timeout_s)
            if text.startswith("[ERROR"):
                last_error = text
                continue
            return {
                "ok": True,
                "response_text": text,
                "attempt": attempt + 1,
                "error": ""
            }
        except Exception as e:
            last_error = str(e)
    return {
        "ok": False,
        "response_text": "",
        "attempt": retries + 1,
        "error": last_error or "unknown_error"
    }


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
        snippet = text[start:end+1]
        try:
            return json.loads(snippet)
        except Exception:
            return None
    return None


def ask_structured_json(prompt: str, retries: int = 2, timeout_s: int = 45, max_response_chars: int = 120000) -> dict:
    res = ask_with_meta(prompt, retries=retries, timeout_s=timeout_s)
    if not res["ok"]:
        return {
            "ok": False,
            "error": res["error"],
            "response_text": "",
            "parsed_json": None,
            "truncated": False,
            "response_chars": 0
        }
    response_text = res["response_text"] or ""
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
        "response_chars": len(response_text)
    }


if __name__ == "__main__":
    print("⚠️ Unofficial Gemini Chatbot (type 'exit' to quit)\n")
    while True:
        user_input = input("You: ")
        if user_input.lower() in ["exit", "quit"]:
            break
        reply = ask(user_input)
        print("Bot:", reply)
