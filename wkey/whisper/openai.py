import os
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

from .io_utils import open_audio_source

load_dotenv()
WHISPER_MODEL = os.environ.get("OPENAI_WHISPER_MODEL", "whisper-1")

_CLIENT = None
_CLIENT_CONFIG = None


def _normalize_base_url(base_url: Optional[str]) -> Optional[str]:
    if not base_url:
        return None
    clean = base_url.rstrip("/")
    if not clean.endswith("/v1"):
        clean += "/v1"
    return clean


def _configure_openai_client() -> OpenAI:
    global _CLIENT, _CLIENT_CONFIG
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    base_url = _normalize_base_url(os.environ.get("OPENAI_BASE_URL"))
    cfg = (api_key, base_url)
    if _CLIENT is None or cfg != _CLIENT_CONFIG:
        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        _CLIENT = OpenAI(**client_kwargs)
        _CLIENT_CONFIG = cfg
    return _CLIENT


def apply_whisper(audio_source, mode: str) -> str:
    if mode not in ("translate", "transcribe"):
        raise ValueError(f"Invalid mode: {mode}")

    client = _configure_openai_client()

    prompt = "Hello, this is a properly structured message. GPT, ChatGPT."
    
    with open_audio_source(audio_source) as audio_file:
        if mode == "translate":
            response = client.audio.translations.create(
                model=WHISPER_MODEL,
                file=audio_file,
                prompt=prompt,
            )
        elif mode == "transcribe":
            response = client.audio.transcriptions.create(
                model=WHISPER_MODEL,
                file=audio_file,
                prompt=prompt,
            )

    return response.text


def _messages_to_response_input(messages):
    formatted = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        if isinstance(content, list):
            # Flatten any structured content into newline-separated text
            text_parts = []
            for part in content:
                if isinstance(part, dict) and "text" in part:
                    text_parts.append(part["text"])
                elif isinstance(part, str):
                    text_parts.append(part)
            content = "\n".join(text_parts)
        formatted.append({"role": role, "content": content})
    return formatted


def _extract_response_text(response) -> str:
    # The responses API can return multiple content blocks; concatenate any text parts.
    texts = []
    output = getattr(response, "output", None)
    if output:
        for item in output:
            if getattr(item, "type", None) != "message":
                continue
            for content in getattr(item, "content", []):
                if getattr(content, "type", None) == "text":
                    text_value = getattr(content, "text", "")
                    if text_value:
                        texts.append(text_value)
    if not texts:
        output_text = getattr(response, "output_text", None)
        if output_text:
            if isinstance(output_text, str):
                texts.append(output_text)
            else:
                try:
                    texts.append("".join(output_text))
                except TypeError:
                    pass
    if not texts:
        raise RuntimeError("No text response returned from OpenAI responses API.")
    return "\n".join(texts).strip()


def _supports_temperature(model_name: str) -> bool:
    normalized = (model_name or "").lower()
    return not normalized.startswith("gpt-5")


def run_chat_completion(messages, model=None, temperature=0.0, max_tokens=1024):
    client = _configure_openai_client()
    payload = _messages_to_response_input(messages)
    model_name = model or "gpt-5-mini"
    request_args = {
        "model": model_name,
        "input": payload,
        "max_output_tokens": max_tokens,
    }
    if _supports_temperature(model_name):
        request_args["temperature"] = temperature
    completion = client.responses.create(**request_args)
    return _extract_response_text(completion)
