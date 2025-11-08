import io
import os
import signal
import threading
import time
import wave

from dotenv import load_dotenv
import sounddevice as sd
from pynput.keyboard import Controller as KeyboardController, Key, Listener

from wkey.whisper import apply_whisper
from wkey.utils import process_transcript, convert_chinese
from wkey.llm_correction import llm_corrector

load_dotenv()
key_label = os.environ.get("WKEY", "ctrl_r")
RECORD_KEY = Key[key_label]
CHINESE_CONVERSION = os.environ.get("CHINESE_CONVERSION")

# This flag determines when to record
recording = False

# This is where we'll store the audio (as bytes)
audio_data = []
audio_lock = threading.Lock()

# This is the sample rate for the audio
sample_rate = 16000

# Keyboard controller
keyboard_controller = KeyboardController()


def _record_and_transcribe(audio_chunks):
    """Write in-memory WAV and return the transcript."""
    if not audio_chunks:
        print("No audio data recorded, probably because the key was pressed for too short a time.")
        return None

    # Join the bytes chunks
    all_audio_bytes = b''.join(audio_chunks)

    audio_buffer = io.BytesIO()
    with wave.open(audio_buffer, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 2 bytes for 'int16'
        wf.setframerate(sample_rate)
        wf.writeframes(all_audio_bytes)

    audio_buffer.seek(0)

    try:
        transcript = apply_whisper(audio_buffer, 'transcribe')
        return transcript
    except Exception as e:
        print(f"Error during transcription: {e}")
        return None

def _process_and_type_transcript(transcript: str):
    """Applies corrections and conversions, then types the final transcript."""
    is_llm_correct_enabled = os.getenv("LLM_CORRECT", "false").lower() in ("true", "1", "yes")
    if is_llm_correct_enabled:
        original_transcript = transcript
        transcript = llm_corrector(transcript)
        if original_transcript != transcript:
            print(f"Before Corrected: {original_transcript}")

    if CHINESE_CONVERSION:
        transcript = convert_chinese(transcript, CHINESE_CONVERSION)
    
    processed_transcript = process_transcript(transcript)
    print(processed_transcript)
    keyboard_controller.type(processed_transcript)


def on_press(key):
    global recording
    global audio_data
    
    if key == RECORD_KEY and not recording:
        recording = True
        with audio_lock:
            audio_data = []
        print("Listening...")

def on_release(key):
    global recording
    global audio_data
    
    if key != RECORD_KEY:
        return

    if not recording:
        return

    recording = False
    print("Transcribing...")

    with audio_lock:
        audio_chunks = audio_data[:]
        audio_data = []

    def worker(chunks):
        transcript = _record_and_transcribe(chunks)
        if transcript:
            _process_and_type_transcript(transcript)

    threading.Thread(target=worker, args=(audio_chunks,), daemon=True).start()


def callback(indata, frames, time, status):
    """This is called (from a separate thread) for each audio block."""
    if status:
        print(status)
    if recording:
        # Copy the bytes because RawInputStream reuses the buffer
        with audio_lock:
            audio_data.append(bytes(indata))


def run(stop_event=None, install_sigint_handler=True):
    """Runs the listener/audio loop until stop_event is set."""
    print(f"wkey is active. Hold down {key_label} to start dictating.")
    internal_event = stop_event or threading.Event()

    listener = Listener(on_press=on_press, on_release=on_release)
    listener.start()

    def _handle_sigint(signum, frame):
        """Allow Ctrl+C to stop the listener and exit cleanly."""
        print("\nReceived Ctrl+C, shutting down...")
        internal_event.set()
        listener.stop()

    previous_handler = None
    if install_sigint_handler:
        previous_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, _handle_sigint)

    try:
        # Use RawInputStream to get bytes directly, avoiding numpy conversion
        with sd.RawInputStream(callback=callback, channels=1, samplerate=sample_rate, dtype='int16'):
            try:
                while listener.is_alive():
                    if internal_event.is_set():
                        listener.stop()
                        break
                    time.sleep(0.1)
            except KeyboardInterrupt:
                if install_sigint_handler:
                    _handle_sigint(signal.SIGINT, None)
                else:
                    internal_event.set()
                    listener.stop()
    finally:
        internal_event.set()
        listener.stop()
        listener.join()
        if install_sigint_handler and previous_handler is not None:
            signal.signal(signal.SIGINT, previous_handler)


def start_service():
    """Starts the wkey service in a background thread."""
    stop_event = threading.Event()
    thread = threading.Thread(target=run, kwargs={"stop_event": stop_event, "install_sigint_handler": False}, daemon=True)
    thread.start()
    return stop_event, thread


def stop_service(stop_event, thread=None, timeout=5):
    """Stops the background service started via start_service."""
    if stop_event:
        stop_event.set()
    if thread:
        thread.join(timeout=timeout)


def main():
    run()


if __name__ == "__main__":
    main()
