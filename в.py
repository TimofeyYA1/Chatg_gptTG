# test_openai.py
from __future__ import annotations
import sys
from openai import OpenAI
from common.config import settings


def print_header():
    print("OPENAI_ENABLED:", settings.OPENAI_ENABLED)
    print("OPENAI_API_KEY set:", bool(settings.OPENAI_API_KEY))
    print("CHAT MODEL:", settings.OPENAI_MODEL_CHAT, " IMAGE MODEL:", settings.OPENAI_MODEL_IMAGE)


def chat_with_best_api(client: OpenAI, model: str) -> str:
    """
    Унифицированный вызов:
    - gpt-5* → Responses API
    - прочие  → Chat Completions API
    Возвращает строку-ответа (короткую).
    """
    user_prompt = "Скажи одно короткое слово: тест"
    max_tokens = min(16, settings.OPENAI_MAX_OUTPUT_TOKENS or 16)
    temperature = float(settings.OPENAI_TEMPERATURE or 0.1)

    # gpt-5 и новые — через Responses API
    if model.lower().startswith("gpt-5"):
        resp = client.responses.create(
            model=model,
            input=[
                {"role": "user", "content": [{"type": "text", "text": user_prompt}]}
            ],
            max_output_tokens=max_tokens,
            temperature=temperature,
        )
        # Унифицированное получение текста из Responses API:
        return (resp.output_text or "").strip()

    # остальное — классический Chat Completions
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": user_prompt}],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return (resp.choices[0].message.content or "").strip()


def test_image(client: OpenAI, model: str) -> int:
    """
    Возвращает длину base64, если ок.
    """
    img = client.images.generate(
        model=model,
        prompt="simple black square icon",
        size="512x512",
        response_format="b64_json",
        n=1,
    )
    return len(img.data[0].b64_json)


def main():
    print_header()

    if not (settings.OPENAI_ENABLED and settings.OPENAI_API_KEY):
        print("⛔ Провайдер выключен или нет ключа")
        sys.exit(1)

    client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=20.0)

    # --- CHAT ---
    try:
        text = chat_with_best_api(client, settings.OPENAI_MODEL_CHAT)
        print("✅ CHAT OK:", text or "(пусто)")
    except Exception as e:
        print("❌ CHAT FAIL:", repr(e))

    # --- IMAGE ---
    try:
        b64len = test_image(client, settings.OPENAI_MODEL_IMAGE)
        print("✅ IMAGE OK: b64 length =", b64len)
    except Exception as e:
        print("❌ IMAGE FAIL:", repr(e))


if __name__ == "__main__":
    main()
