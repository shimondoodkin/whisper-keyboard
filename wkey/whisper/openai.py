import os
import openai
from dotenv import load_dotenv

from .io_utils import open_audio_source

load_dotenv()
openai.api_key = os.environ["OPENAI_API_KEY"]
WHISPER_MODEL = "whisper-1"

def apply_whisper(audio_source, mode: str) -> str:
    if mode not in ("translate", "transcribe"):
        raise ValueError(f"Invalid mode: {mode}")

    prompt = "Hello, this is a properly structured message. GPT, ChatGPT."
    
    with open_audio_source(audio_source) as audio_file:
        if mode == "translate":
            response = openai.Audio.translate(WHISPER_MODEL, audio_file, prompt=prompt)
        elif mode == "transcribe":
            response = openai.Audio.transcribe(WHISPER_MODEL, audio_file, prompt=prompt)

    return response["text"]
