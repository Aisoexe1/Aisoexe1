"""Gemini solver via raw HTTP — no google-generativeai dependency."""
import json
import os
from typing import AsyncGenerator

import httpx

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.0-flash:streamGenerateContent"
)

_SYSTEM = (
    "Ти академічний помічник студента університету. "
    "Виконуй навчальні завдання якісно, структуровано і повно. "
    "Відповідай мовою завдання (українська або російська). "
    "Використовуй заголовки, списки, формули там де це доречно."
)


async def solve_stream(
    title: str,
    description: str,
    course: str = "",
) -> AsyncGenerator[str, None]:
    """Stream Gemini response chunks for an assignment."""
    prompt = (
        f"Курс: {course}\n"
        f"Назва завдання: {title}\n\n"
        f"Умова завдання:\n{description}\n\n"
        "Виконай це завдання повністю та якісно."
    )

    payload = {
        "system_instruction": {"parts": [{"text": _SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 8192},
    }

    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            "POST",
            GEMINI_URL,
            params={"key": GEMINI_API_KEY, "alt": "sse"},
            json=payload,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                raw = line[6:].strip()
                if raw in ("", "[DONE]"):
                    continue
                try:
                    data = json.loads(raw)
                    text = (
                        data.get("candidates", [{}])[0]
                        .get("content", {})
                        .get("parts", [{}])[0]
                        .get("text", "")
                    )
                    if text:
                        yield text
                except (json.JSONDecodeError, IndexError, KeyError):
                    continue
