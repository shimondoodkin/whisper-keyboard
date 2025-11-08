import os
from dotenv import load_dotenv

load_dotenv()

backend = os.environ.get("WHISPER_BACKEND")

def _load_backend(name: str):
    if name == "openai":
        from .openai import apply_whisper
    elif name == "groq":
        from .groq import apply_whisper
    elif name == "whisperx":
        from .whisperx import apply_whisper
    elif name == "insanely-whisper":
        from .insanely_whisper import apply_whisper
    else:
        raise ImportError(f"Invalid whisper backend: {name}")
    return apply_whisper

if backend:
    apply_whisper = _load_backend(backend)
else:
    groq_key = os.environ.get("GROQ_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")
    if groq_key:
        apply_whisper = _load_backend("groq")
    elif openai_key:
        apply_whisper = _load_backend("openai")
    else:
        raise ImportError(
            "No Whisper backend configured: set WHISPER_BACKEND or provide GROQ_API_KEY / OPENAI_API_KEY"
        )
