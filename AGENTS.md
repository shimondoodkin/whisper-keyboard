# Repository Guidelines

## Project Structure & Modules
- Core source lives in `wkey/` with submodules for tray UI (`tray_app.py`), Whisper backends (`whisper/`), configuration helpers (`config.py`), and the CLI entry point (`wkey.py`).
- Packaging/entry glue: `setup.py`, `run_wkey.py`, and console scripts defined in `setup.py`.
- Assets/config examples: `.env.example`, `requirements.txt`, and the persisted settings file created at runtime (`~/.wkey.json`).
- Tests are not yet present; add new suites under `tests/` if you introduce them.

## Build, Test, and Run
- Install deps once: `pip install -r requirements.txt`.
- Editable install during development: `pip install -e .`.
- CLI listener: `python run_wkey.py` (inside the repo) or `wkey` after installation.
- Tray companion: `python -m wkey.tray_app` or `wkey-tray`.
- Package build: `python -m build` (ensure `build` is installed) to verify distributions before publishing.

## Coding Style & Naming
- Follow PEP 8 (4-space indents, lowercase_with_underscores for functions/modules, CapWords for classes).
- Maintain type hints where present and prefer explicit dataclasses/config objects over dicts.
- Keep logging human-readable; avoid printing secrets. Use the existing logging patterns in `wkey/wkey.py`.
- Configuration keys should match existing environment variable names (e.g., `WHISPER_BACKEND`, `GROQ_API_KEY`).

## Testing Guidelines
- Smoke-test the CLI (`python run_wkey.py`) and tray app after meaningful changes; capture console output in PR notes.
- If adding automated tests, use `pytest` under `tests/` named `test_*.py`, and document any fixtures.
- Verify audio capture/transcription by dictating a short sample; include reproduction steps when filing bugs.

## Commit & Pull Request Workflow
- Commit messages: short imperative summaries (`Update metadata and docs`, `Fix tray hotkey capture`). Group related changes.
- Before committing, run at least the CLI smoke test; mention gaps if something cannot be tested locally.
- Pull requests should describe the change, reference related issues, note testing performed, and include screenshots/GIFs when UI behavior changes (tray dialogs, notifications).

## Security & Configuration Tips
- Never commit actual API keys; rely on `.env` or `%USERPROFILE%\.wkey.json`.
- Document any new environment variables in both `README.md` and the tray settings dialog to keep UX consistent.
- Respect user privacy: ensure audio files are temporary and redact sensitive log data before sharing.
