# whisper-keyboard

Hands-free typing powered by OpenAI/Groq Whisper. Hold your chosen hotkey, speak, release, and watch the text appear in any application. whisper-keyboard captures audio locally, transcribes it via Whisper (including Whisper Large V3 at roughly **$0.03 per hour of transcription**), applies optional corrections, and injects the text as native keystrokes. A lightweight system-tray companion keeps the service running quietly in the background.

Video demo: https://www.youtube.com/watch?v=VnFtVR72jM4&feature=youtu.be

---

## Features

- 🎙️ **Press-to-talk dictation** – hold a global hotkey (default `right ctrl`), speak, and release to insert text anywhere.
- 🧠 **Optional LLM post-processing** – automatically clean up transcripts or convert between Simplified/Traditional Chinese.
- 🪟 **System-tray companion** – launch `wkey` minimized, view an About dialog, and exit via tray menu, About dialog, or `Ctrl+C`.
- 🧩 **Drop-in API keys** – works with OpenAI or Groq Whisper; choose at runtime via environment variables.
- 🛡️ **Local audio buffering** – audio stays on your machine until you explicitly send it to the Whisper backend.

---

## Installation

### From PyPI

```bash
pip install wkey
```

To install directly from this GitHub fork:

```bash
pip install git+https://github.com/shimondoodkin/whisper-keyboard.git
```

### From source tree

```bash
git clone https://github.com/shimondoodkin/whisper-keyboard.git
cd whisper-keyboard
pip install -r requirements.txt
```

---

## Configuration

Configure the app through environment variables (put them in `.env`, your shell profile, or the system environment) **or** via the persistent settings file stored at `~/.wkey.json`. The tray application’s Settings dialog edits this file; whenever it exists, wkey prints the full path that is being loaded. If the file is empty, wkey falls back to the current environment variables rather than overwriting them.

- `GROQ_API_KEY` or `OPENAI_API_KEY`: provide at least one. If both exist, Groq is preferred unless you set `WHISPER_BACKEND`.
- `WHISPER_BACKEND` (optional): choose `groq`, `openai`, or any backend implemented in `wkey.whisper`.
- `WKEY` (optional): pynput key name that toggles recording (default `ctrl_r`). Use the bundled `fkey` helper to discover key names.
- `LLM_CORRECT` (optional): set to `true` to run transcripts through `llm_corrector`.
- `CHINESE_CONVERSION` (optional): OpenCC conversion code such as `s2t`, `t2s`, etc.

Example:

```bash
export GROQ_API_KEY=sk-...
export WKEY=shift_r
export WHISPER_BACKEND=groq
```

---

## Usage

### Terminal mode

Run `wkey` (after installing via pip) or `python run_wkey.py` (inside the repo). You’ll see:

```
wkey is active. Hold down ctrl_r to start dictating.
```

- Hold the configured key: “Listening…” appears.
- Release it: “Transcribing…” appears, then the processed transcript prints and is typed into the focused window.
- Press `Ctrl+C` to exit cleanly.

### System-tray mode

Launch `wkey-tray` (pip) or `python -m wkey.tray_app` (repo clone).

- A "W" icon appears in your notification area immediately; the listener runs in the background.
- Click/double-click the icon to open the Settings dialog: edit Groq/OpenAI keys, pick a backend and hotkey (with live key-capture history, including left/right modifier combos like `ctrl_r+shift_r`), toggle LLM correction, set Chinese conversion, and Apply/Save without restarting; dictation auto-pauses while the dialog is open so your capture presses don't trigger recordings.
- Right-click the tray icon for a context menu with **Settings**, **Pause dictation**, and **Exit**.
- Press `Ctrl+C` in the launching terminal to shut down the tray app as well.

Both launchers share the same service code, so improvements carry over automatically.

---

## Running options

After installing from **PyPI (or via `pip install git+...`)**:

- CLI listener: `wkey`
- Tray companion: `wkey-tray`

When working from the **cloned repository**:

- CLI listener: `python run_wkey.py` (or `python -m wkey`)
- Tray companion: `python -m wkey.tray_app`

### Running without a console window (Windows)

Use `pythonw` to suppress the console:

```powershell
pythonw -m wkey.tray_app
```

Make sure `pythonw.exe` points to the same interpreter where you installed `wkey`.

### Windows auto-start options

- **Startup folder**: create a shortcut in `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup` that targets `pythonw.exe -m wkey.tray_app`. Set "Start in" to the folder containing your `.env` file if needed, or rely on `%USERPROFILE%\.wkey.json` for configuration.
- **Task Scheduler**:
  1. Open Task Scheduler → “Create Task…”.
  2. “Run only when user is logged on” (ensures tray icon is visible) and check “Run with highest privileges” if you plan to dictate into elevated apps.
  3. Trigger: “At log on”.
  4. Action: “Start a program”, Program/script `pythonw.exe`, Arguments `-m wkey.tray_app`, Start in `%USERPROFILE%\path\to\whisper-keyboard`.
  5. Save and test the task.

Either method launches the tray app at login with no visible console window.

## Create API accounts

1. **Groq** – visit https://console.groq.com/, create an account, then open the API Keys page to generate a token. Groq currently offers a free API tier, so transcription can be effectively free. Set it as `GROQ_API_KEY`.
2. **OpenAI** – visit https://platform.openai.com/, sign in, and create a secret key under View API Keys. Set it as `OPENAI_API_KEY`.

If you enable both, set `WHISPER_BACKEND` to control which service is used.

## Platform requirements

### Ubuntu / Debian

- Install PortAudio headers before `pip install sounddevice`:

  ```bash
  sudo apt-get install portaudio19-dev
  ```

### macOS

- Grant microphone and accessibility permissions to the terminal or app hosting `wkey`.
  - **System Settings → Privacy & Security → Microphone**: enable your terminal.
  - **System Settings → Privacy & Security → Accessibility**: enable your terminal/app.
- Restart the terminal after changing permissions.

### Windows

- Confirmed working with both terminal and tray modes.
- Ensure the target app and wkey run with the **same privilege level** (mixing Administrator/non-Administrator prevents synthetic keystrokes).
- If you run `wkey` elevated, run the target editor elevated too, and vice versa.

---

## Troubleshooting

- **No keystrokes in the destination app** – verify privilege levels match and that no other macro/hotkey tools intercept the events.
- **“Listening…” never appears** – double-check `WKEY` matches the key name from `fkey`, and that no other process is grabbing the key.
- **Audio not captured** – confirm the default recording device is active; set `SOUNDDEVICE_DEVICE` (see `sounddevice` docs) if you need a specific input.
- **Tray app won’t exit** – ensure you’re on the latest version; `Ctrl+C`, tray menu exit, and About dialog exit all share the same shutdown path now.

Collect logs by running with `PYTHONWARNINGS=default` or adding prints in `wkey/wkey.py`.

---

## Security considerations

- Audio is recorded locally but sent to the selected Whisper backend for transcription. Treat dictated content as sensitive.
- The resulting text is typed directly into the active application. Malicious prompts could trigger shortcuts or commands. Keep the hotkey pressed only while dictating trusted content.
- Grant microphone/keyboard accessibility permissions only to applications you trust, and review them periodically.

---

## Contributing

Pull requests and bug reports are welcome on https://github.com/shimondoodkin/whisper-keyboard. Ideas for improvement:

- Multi-language hotkey support
- Configurable output destinations (clipboard + typing)
- Pause/resume buttons in the tray UI

Open an issue describing the change before large rewrites, and run lint/tests where applicable. Use `git commit -s` if you require signed commits.

---

## License

MIT © Vlad Gheorghe. Use at your own risk; API usage incurs the costs associated with your chosen Whisper provider (roughly $0.36/hour for OpenAI at the time of writing).
