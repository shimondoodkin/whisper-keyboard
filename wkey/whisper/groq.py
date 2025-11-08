import os

from dotenv import load_dotenv
from groq import Groq

from .io_utils import open_audio_source

load_dotenv()
WHISPER_LANGUAGE = os.environ.get("WHISPER_LANGUAGE")

_CLIENT = None
_CLIENT_CONFIG = None


def _get_client():
    global _CLIENT, _CLIENT_CONFIG
    cfg = (os.environ.get("GROQ_API_KEY"), os.environ.get("GROQ_BASE_URL", "https://api.groq.com"))
    if not cfg[0]:
        raise RuntimeError("GROQ_API_KEY is not set.")
    if _CLIENT is None or cfg != _CLIENT_CONFIG:
        _CLIENT = Groq(api_key=cfg[0], base_url=cfg[1])
        _CLIENT_CONFIG = cfg
    return _CLIENT


def apply_whisper(audio_source, mode: str) -> str:

    if mode not in ("translate", "transcribe"):
        raise ValueError(f"Invalid mode: {mode}")

    prompt = "Hello, this is a properly structured message. GPT, ChatGPT."
    model = os.environ.get("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")
    client = _get_client()
    
    with open_audio_source(audio_source) as audio_file:
        if mode == "translate":
            response = client.audio.translations.create(
                file=audio_file,
                model=model,
                prompt=prompt,
            )
        elif mode == "transcribe":
            transcription_options = {
                "file": audio_file,
                "model": model,
                "prompt": prompt,
            }
            if WHISPER_LANGUAGE:
                transcription_options["language"] = WHISPER_LANGUAGE
            response = client.audio.transcriptions.create(**transcription_options)

    return response.text

