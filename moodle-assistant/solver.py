"""Gemini-powered assignment solver (free tier)."""
import os
from typing import AsyncGenerator
import google.generativeai as genai
from google.generativeai.types import GenerationConfig

genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))

_model = genai.GenerativeModel(
    model_name="gemini-2.0-flash",
    generation_config=GenerationConfig(temperature=0.7, max_output_tokens=8192),
    system_instruction=(
        "Ти академічний помічник студента університету. "
        "Виконуй навчальні завдання якісно, структуровано і повно. "
        "Відповідай мовою завдання (українська або російська). "
        "Використовуй заголовки, списки, формули там де це доречно."
    ),
)


async def solve_stream(
    title: str,
    description: str,
    course: str = "",
) -> AsyncGenerator[str, None]:
    """Stream Gemini response for an assignment."""
    prompt = (
        f"Курс: {course}\n"
        f"Назва завдання: {title}\n\n"
        f"Умова завдання:\n{description}\n\n"
        "Виконай це завдання повністю та якісно."
    )

    response = await _model.generate_content_async(prompt, stream=True)
    async for chunk in response:
        if chunk.text:
            yield chunk.text
