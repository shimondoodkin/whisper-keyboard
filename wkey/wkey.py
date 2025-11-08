import array
import io
import os
import signal
import threading
import time
import traceback
import wave

from dotenv import load_dotenv
import sounddevice as sd
from pynput import mouse as pynput_mouse
from pynput.keyboard import Controller as KeyboardController, Key, Listener, KeyCode

from wkey.config import SETTINGS_PATH, apply_settings, load_settings
from wkey.whisper import apply_whisper
from wkey.utils import process_transcript, convert_chinese
from wkey.llm_correction import llm_corrector

def _coerce_bool(value, fallback):
    if value is None:
        return bool(fallback)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return False
        return stripped.lower() in ("1", "true", "yes", "on")
    return bool(value)


def _env_bool(name, fallback):
    return _coerce_bool(os.environ.get(name), fallback)


load_dotenv()
current_settings, has_user_overrides = load_settings()
if has_user_overrides:
    apply_settings(current_settings, clear_missing=True)

key_label = os.environ.get("WKEY", current_settings.get("hotkey", "ctrl_r"))
mouse_button_label = os.environ.get("WKEY_MOUSE_BUTTON", current_settings.get("mouse_button", ""))
keyboard_enabled = _env_bool("WKEY_KEYBOARD_ENABLED", current_settings.get("enable_keyboard_shortcut", True))
mouse_enabled = _env_bool("WKEY_MOUSE_ENABLED", current_settings.get("enable_mouse_shortcut", True))
continuous_listen = _env_bool("WKEY_CONTINUOUS_LISTEN", current_settings.get("continuous_listen", True))
CHINESE_CONVERSION = os.environ.get("CHINESE_CONVERSION")

HOTKEY_PARTS = set()
pressed_keys = set()
MOUSE_BUTTON = None
mouse_pressed = False
paused = False
recording = False
audio_data = []
audio_lock = threading.Lock()
audio_stream_lock = threading.Lock()
audio_stream = None

def _parse_hotkey(label: str):
    parts = []
    for raw in label.split("+"):
        part = raw.strip()
        if not part:
            continue
        if len(part) == 1:
            parts.append(part.lower())
        else:
            try:
                Key[part]
            except KeyError:
                raise ValueError(f"Unknown key name '{part}'")
            parts.append(part)
    if not parts:
        raise ValueError("Hotkey must include at least one key")
    return parts

def _key_name(key):
    if isinstance(key, Key):
        return key.name
    if isinstance(key, KeyCode) and key.char:
        return key.char.lower()
    return None

def _set_record_key(label: str):
    global key_label, HOTKEY_PARTS
    try:
        if not label:
            HOTKEY_PARTS = set()
            pressed_keys.clear()
            key_label = ""
            os.environ.pop("WKEY", None)
            print("Keyboard hotkey cleared.")
            return
        parts = set(_parse_hotkey(label))
        HOTKEY_PARTS = parts
        pressed_keys.clear()
        key_label = label
        os.environ["WKEY"] = label
        print(f"Set recording hotkey to {label}")
    except ValueError as exc:
        _report_error(f"Invalid hotkey '{label}': {exc}. Keeping previous key: {key_label}.")

_set_record_key(key_label)


def _parse_mouse_button(label: str):
    if not label:
        return None
    normalized = label.strip().lower()
    mapping = {
        "middle": pynput_mouse.Button.middle,
        "mouse3": pynput_mouse.Button.middle,
        "button3": pynput_mouse.Button.middle,
        "x1": pynput_mouse.Button.x1,
        "mouse4": pynput_mouse.Button.x1,
        "button4": pynput_mouse.Button.x1,
        "x2": pynput_mouse.Button.x2,
        "mouse5": pynput_mouse.Button.x2,
        "button5": pynput_mouse.Button.x2,
    }
    if normalized in mapping:
        return mapping[normalized]
    raise ValueError(f"Unknown mouse button '{label}' (supported: middle, x1, x2)")


def _set_mouse_button(label: str):
    global mouse_button_label, MOUSE_BUTTON, mouse_pressed
    try:
        button = _parse_mouse_button(label)
        MOUSE_BUTTON = button
        mouse_pressed = False
        mouse_button_label = label or ""
        if button is None:
            os.environ.pop("WKEY_MOUSE_BUTTON", None)
            print("Mouse button trigger disabled.")
        else:
            os.environ["WKEY_MOUSE_BUTTON"] = label
            print(f"Set recording mouse button to {label}")
    except ValueError as exc:
        _report_error(f"Invalid mouse button '{label}': {exc}. Keeping previous value: {mouse_button_label or 'disabled'}.")


_set_mouse_button(mouse_button_label)


def _set_keyboard_enabled(enabled: bool):
    global keyboard_enabled, pressed_keys
    keyboard_enabled = bool(enabled)
    if not keyboard_enabled:
        pressed_keys.clear()
    os.environ["WKEY_KEYBOARD_ENABLED"] = "true" if keyboard_enabled else "false"


def _set_mouse_enabled(enabled: bool):
    global mouse_enabled, mouse_pressed
    mouse_enabled = bool(enabled)
    if not mouse_enabled:
        mouse_pressed = False
    os.environ["WKEY_MOUSE_ENABLED"] = "true" if mouse_enabled else "false"


_set_keyboard_enabled(keyboard_enabled)
_set_mouse_enabled(mouse_enabled)

_error_handler = None

def set_error_handler(handler):
    global _error_handler
    _error_handler = handler

def _report_error(message, exc=None):
    if exc:
        print(f"{message}: {exc}")
        traceback.print_exception(type(exc), exc, exc.__traceback__)
    else:
        print(message)
    if _error_handler:
        try:
            _error_handler(message if not exc else f"{message}: {exc}")
        except Exception:
            pass


def refresh_configuration(settings=None, clear_missing=True):
    """Reapply configuration (hotkey + conversions) from provided settings or env."""
    global CHINESE_CONVERSION
    if settings:
        apply_settings(settings, clear_missing=clear_missing)
    hotkey_env = os.environ.get("WKEY") if "WKEY" in os.environ else None
    hotkey = hotkey_env if hotkey_env is not None else (settings or {}).get("hotkey", key_label)
    _set_record_key(hotkey)
    mouse_env = os.environ.get("WKEY_MOUSE_BUTTON") if "WKEY_MOUSE_BUTTON" in os.environ else None
    mouse_button = mouse_env if mouse_env is not None else (settings or {}).get("mouse_button", mouse_button_label)
    _set_mouse_button(mouse_button)
    kb_env = os.environ.get("WKEY_KEYBOARD_ENABLED") if "WKEY_KEYBOARD_ENABLED" in os.environ else None
    kb_enabled = _coerce_bool(kb_env, (settings or {}).get("enable_keyboard_shortcut", keyboard_enabled))
    _set_keyboard_enabled(kb_enabled)
    mouse_env_enabled = os.environ.get("WKEY_MOUSE_ENABLED") if "WKEY_MOUSE_ENABLED" in os.environ else None
    mouse_enabled_flag = _coerce_bool(mouse_env_enabled, (settings or {}).get("enable_mouse_shortcut", mouse_enabled))
    _set_mouse_enabled(mouse_enabled_flag)
    CHINESE_CONVERSION = os.environ.get("CHINESE_CONVERSION")
    continuous_env = os.environ.get("WKEY_CONTINUOUS_LISTEN") if "WKEY_CONTINUOUS_LISTEN" in os.environ else None
    continuous_value = _coerce_bool(continuous_env, (settings or {}).get("continuous_listen", continuous_listen))
    _set_continuous_listen(continuous_value)

# This is the sample rate for the audio
sample_rate = 16000

# Keyboard controller
keyboard_controller = KeyboardController()


def _audio_callback(indata, frames, time_info, status):
    """Capture callback for sounddevice stream."""
    if status:
        print(status)
    if recording:
        with audio_lock:
            audio_data.append(bytes(indata))


def _start_audio_capture():
    """Start microphone stream only when recording begins."""
    global audio_stream
    with audio_stream_lock:
        if audio_stream is not None:
            return True
        try:
            stream = sd.RawInputStream(callback=_audio_callback, channels=1, samplerate=sample_rate, dtype='int16')
            stream.start()
            audio_stream = stream
            return True
        except Exception as exc:
            audio_stream = None
            _report_error("Failed to start audio capture", exc)
            return False


def _stop_audio_capture(force: bool = False):
    """Stop the microphone stream when dictation ends."""
    global audio_stream
    if not force and continuous_listen:
        return
    with audio_stream_lock:
        stream = audio_stream
        audio_stream = None
    if stream is None:
        return
    try:
        stream.stop()
    except Exception as exc:
        _report_error("Failed to stop audio capture", exc)
    finally:
        try:
            stream.close()
        except Exception:
            pass


def _set_continuous_listen(enabled: bool):
    global continuous_listen
    continuous_listen = bool(enabled)
    os.environ["WKEY_CONTINUOUS_LISTEN"] = "true" if continuous_listen else "false"
    if continuous_listen and not paused:
        _start_audio_capture()
    elif not continuous_listen and not recording:
        _stop_audio_capture(force=True)


def _is_silence(raw_audio: bytes, silence_threshold: int = 300, min_samples: int = 1600) -> bool:
    """Return True when the captured buffer contains only near-zero samples."""
    if not raw_audio:
        return True

    # Require enough samples (~0.1s) to make a decision.
    if len(raw_audio) < min_samples * 2:
        return True

    samples = array.array('h')
    samples.frombytes(raw_audio)
    peak = max(abs(sample) for sample in samples)
    return peak < silence_threshold


_set_continuous_listen(continuous_listen)


def _hotkey_active():
    return keyboard_enabled and bool(HOTKEY_PARTS) and HOTKEY_PARTS.issubset(pressed_keys)


def _mouse_active():
    return mouse_enabled and MOUSE_BUTTON is not None and mouse_pressed


def _triggers_active():
    if keyboard_enabled and mouse_enabled:
        return _hotkey_active() or _mouse_active()
    if keyboard_enabled:
        return _hotkey_active()
    if mouse_enabled:
        return _mouse_active()
    return False


def _mouse_label_hint():
    mapping = {
        "middle": "middle mouse button",
        "x1": "thumb button 1",
        "x2": "thumb button 2",
    }
    label = mouse_button_label.strip().lower() if mouse_button_label else ""
    return mapping.get(label, f"{mouse_button_label} mouse button") if label else ""


def _trigger_hint():
    hints = []
    if keyboard_enabled and key_label:
        hints.append(f"hold down {key_label}")
    if mouse_enabled:
        mouse_hint = _mouse_label_hint()
        if mouse_hint:
            hints.append(f"hold the {mouse_hint}")
    return " or ".join(hints)


def _record_and_transcribe(audio_chunks):
    """Write in-memory WAV and return the transcript."""
    if not audio_chunks:
        print("No audio data recorded, probably because the key was pressed for too short a time.")
        return None

    # Join the bytes chunks
    all_audio_bytes = b''.join(audio_chunks)

    if _is_silence(all_audio_bytes):
        print("No speech detected, skipping transcription.")
        return None

    audio_buffer = io.BytesIO()
    with wave.open(audio_buffer, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 2 bytes for 'int16'
        wf.setframerate(sample_rate)
        wf.writeframes(all_audio_bytes)

    audio_buffer.seek(0)
    audio_buffer.name = "recording.wav"

    try:
        transcript = apply_whisper(audio_buffer, 'transcribe')
        return transcript
    except Exception as e:
        _report_error("Error during transcription", e)
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
    if paused:
        return

    name = _key_name(key)
    if name:
        pressed_keys.add(name)

    _maybe_start_recording()

def on_release(key):
    if paused:
        return

    name = _key_name(key)
    if name:
        pressed_keys.discard(name)

    _maybe_stop_recording()


def on_click(x, y, button, pressed):
    global mouse_pressed
    if paused or MOUSE_BUTTON is None:
        return
    if button != MOUSE_BUTTON:
        return
    mouse_pressed = pressed
    if pressed:
        _maybe_start_recording()
    else:
        _maybe_stop_recording()


def _maybe_start_recording():
    global recording, audio_data
    if recording or paused or not _triggers_active():
        return
    if not _start_audio_capture():
        return
    recording = True
    with audio_lock:
        audio_data = []
    print("Listening...")


def _maybe_stop_recording():
    global recording, audio_data
    if not recording or _triggers_active():
        return
    recording = False
    print("Transcribing...")
    _stop_audio_capture()

    with audio_lock:
        audio_chunks = audio_data[:]
        audio_data = []

    def worker(chunks):
        transcript = _record_and_transcribe(chunks)
        if transcript:
            _process_and_type_transcript(transcript)

    threading.Thread(target=worker, args=(audio_chunks,), daemon=True).start()

def run(stop_event=None, install_sigint_handler=True):
    """Runs the listener/audio loop until stop_event is set."""
    hint = _trigger_hint()
    if hint:
        print(f"wkey is active. {hint} to start dictating.")
    else:
        print("wkey is running, but both keyboard and mouse triggers are disabled.")
    internal_event = stop_event or threading.Event()

    listener = Listener(on_press=on_press, on_release=on_release)
    listener.start()

    mouse_listener = None
    try:
        mouse_listener = pynput_mouse.Listener(on_click=on_click)
        mouse_listener.start()
    except Exception as exc:
        _report_error("Failed to start mouse listener", exc)

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
        _stop_audio_capture(force=True)
        if mouse_listener:
            mouse_listener.stop()
            mouse_listener.join()
        if install_sigint_handler and previous_handler is not None:
            signal.signal(signal.SIGINT, previous_handler)


def start_service():
    """Starts the wkey service in a background thread."""
    stop_event = threading.Event()
    thread = threading.Thread(target=run, kwargs={"stop_event": stop_event, "install_sigint_handler": False}, daemon=True)
    thread.start()
    return stop_event, thread


def set_paused(value: bool):
    """Enable/disable dictation without stopping the service."""
    global paused, recording
    if value and not paused:
        print("Dictation paused.")
    elif not value and paused:
        print("Dictation resumed.")
    paused = value
    if paused:
        if recording:
            recording = False
        _stop_audio_capture(force=True)
        with audio_lock:
            audio_data = []
    else:
        if continuous_listen:
            _start_audio_capture()


def stop_service(stop_event, thread=None, timeout=5):
    """Stops the background service started via start_service."""
    if stop_event:
        stop_event.set()
    if thread:
        thread.join(timeout=timeout)
    _stop_audio_capture(force=True)


def main():
    run()


if __name__ == "__main__":
    main()
