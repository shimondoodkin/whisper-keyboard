import os
import os

from dotenv import load_dotenv
import openai

from .io_utils import open_audio_source

load_dotenv()
WHISPER_MODEL = os.environ.get("OPENAI_WHISPER_MODEL", "whisper-1")


def _configure_openai_client():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    openai.api_key = api_key
    base = os.environ.get("OPENAI_BASE_URL")
    if base:
        openai.api_base = base.rstrip("/") + ("" if base.rstrip("/").endswith("/v1") else "/v1")
    else:
        openai.api_base = "https://api.openai.com/v1"


def apply_whisper(audio_source, mode: str) -> str:
    if mode not in ("translate", "transcribe"):
        raise ValueError(f"Invalid mode: {mode}")

    _configure_openai_client()

    prompt = "Hello, this is a properly structured message. GPT, ChatGPT."
    
    with open_audio_source(audio_source) as audio_file:
        if mode == "translate":
            response = openai.Audio.translate(WHISPER_MODEL, audio_file, prompt=prompt)
        elif mode == "transcribe":
            response = openai.Audio.transcribe(WHISPER_MODEL, audio_file, prompt=prompt)

    return response["text"]


def run_chat_completion(messages, model=None, temperature=0.0, max_tokens=1024):
    _configure_openai_client()
    model_name = model or "gpt-5-mini"
    response = openai.ChatCompletion.create(
        model=model_name,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return response["choices"][0]["message"]["content"].strip()
