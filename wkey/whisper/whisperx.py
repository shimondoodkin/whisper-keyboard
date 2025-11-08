import os
import requests

from .io_utils import open_audio_source

def apply_whisper(audio_source, mode: str) -> str:
    """
    Calls the whisperX API to transcribe or translate an audio file.
    """
    # --- Configuration from environment variables ---
    baseurl = os.environ.get("WHISPERX_BASEURL", "http://localhost:9000")
    lang = os.environ.get("WHISPER_LANGUAGE")
    model = os.environ.get("WHISPERX_MODEL", "large-v3")
    batch_size = os.environ.get("WHISPERX_BATCH_SIZE", "32")
    chunk_size = os.environ.get("WHISPERX_CHUNK_SIZE", "3")
    alignment = os.environ.get("WHISPERX_ALIGNMENT", "false")
    diarization = os.environ.get("WHISPERX_DIARIZATION", "false")
    return_char_alignments = os.environ.get("WHISPERX_RETURN_CHAR_ALIGNMENTS", "false")

    # --- Prepare file and parameters ---
    mime_type = "audio/wav"

    params = {
        "language": lang,
        "task": mode, # 'transcribe' or 'translate'
        "model": model,
        "batch_size": batch_size,
        "chunk_size": chunk_size,
        "alignment": alignment,
        "diarization": diarization,
        "return_char_alignments": return_char_alignments,
        "is_async": "false"
    }

    # --- POST request to start transcription ---
    try:
        with open_audio_source(audio_source) as f:
            filename = getattr(f, "name", "recording.wav")
            files = {"file": (os.path.basename(filename), f, mime_type)}
            post_url = f"{baseurl}/speech-to-text"
            response = requests.post(post_url, params=params, files=files, timeout=60)
            response.raise_for_status()
        
        task_info = response.json()
        identifier = task_info.get("identifier")
        if not identifier:
            print(f"Error: Could not get task identifier from response: {task_info}")
            return ""

        # --- GET request to fetch the result ---
        get_url = f"{baseurl}/task/{identifier}/txt"
        result_response = requests.get(get_url, timeout=10)
        result_response.raise_for_status()
        text = "".join(result_response.text.split("\n")).strip()

    except requests.exceptions.RequestException as e:
        print(f"Error during API call: {e}")
        text = ""

    return text
