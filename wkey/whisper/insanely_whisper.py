import os
import requests

from .io_utils import open_audio_source

def apply_whisper(audio_source, mode: str) -> str:
    """
    Calls the insanely-fast-whisper API to transcribe an audio file.
    Note: The 'mode' (transcribe/translate) is handled by the API based on the language.
    """
    # --- Configuration from environment variables ---
    baseurl = os.environ.get("INSANELY_WHISPER_BASEURL", "http://localhost:9000")
    lang = os.environ.get("WHISPER_LANGUAGE")
    diarise_audio = os.environ.get("INSANELY_WHISPER_DIARISE", "false").lower()

    # --- Step 1: Upload the audio file ---
    try:
        with open_audio_source(audio_source) as f:
            filename = getattr(f, "name", "recording.wav")
            files = {"file": (os.path.basename(filename), f, "audio/wav")}
            upload_url = f"{baseurl}/files"
            upload_response = requests.post(upload_url, files=files, timeout=300)
            upload_response.raise_for_status()
        
        upload_info = upload_response.json()
        uuid_file = upload_info.get("filename")
        if not uuid_file:
            return f"Error: Could not get filename from upload response: {upload_info}"

    except requests.exceptions.RequestException as e:
        return f"Error during file upload: {e}"

    # --- Step 2: Send the transcription request ---
    try:
        transcribe_url = f"{baseurl}/"
        payload = {
            "url": f"{baseurl}/files/{uuid_file}",
            "language": lang,
            "formats": ["txt"], # We only need the plain text output
            "diarise_audio": diarise_audio
        }
       
        transcribe_response = requests.post(transcribe_url, json=payload, timeout=300)
        transcribe_response.raise_for_status()

        result_info = transcribe_response.json()
        transcribed_text = result_info.get("output", {}).get("txt")
        transcribed_text = "".join(transcribed_text.split("\n")).strip()

        if transcribed_text is None:
            print(f"Error: Could not find 'txt' output in response: {result_info}")
            return ""
        
        return transcribed_text

    except requests.exceptions.RequestException as e:
        print(f"Error during transcription request: {e}")
        return ""

    return ""
