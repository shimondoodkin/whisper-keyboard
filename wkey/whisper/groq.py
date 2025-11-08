import os

from dotenv import load_dotenv
from groq import Groq

from .io_utils import open_audio_source

load_dotenv()
client = Groq(
    api_key=os.environ.get("GROQ_API_KEY"),
    base_url=os.environ.get("GROQ_BASE_URL", "https://api.groq.com"),
)
WHISPER_MODEL = os.environ.get("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")
WHISPER_LANGUAGE = os.environ.get("WHISPER_LANGUAGE")


def apply_whisper(audio_source, mode: str) -> str:

    if mode not in ("translate", "transcribe"):
        raise ValueError(f"Invalid mode: {mode}")

    prompt = "Hello, this is a properly structured message. GPT, ChatGPT."
    
    with open_audio_source(audio_source) as audio_file:
        if mode == "translate":
            response = client.audio.translations.create(
                file=audio_file,
                model=WHISPER_MODEL,
                prompt=prompt,
            )
        elif mode == "transcribe":
            transcription_options = {
                "file": audio_file,
                "model": WHISPER_MODEL,
                "prompt": prompt,
            }
            if WHISPER_LANGUAGE:
                transcription_options["language"] = WHISPER_LANGUAGE
            response = client.audio.transcriptions.create(**transcription_options)

    return response.text

