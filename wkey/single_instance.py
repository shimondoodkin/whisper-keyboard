"""PID-file based single-instance helper for wkey."""
from __future__ import annotations

import atexit
import json
import os
import signal
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil


class SingleInstanceError(RuntimeError):
    """Raised when a second instance cannot take over."""


def _boot_signature() -> float:
    """Return the current system boot time as a stable signature."""
    try:
        return float(psutil.boot_time())
    except Exception:
        return 0.0


def _current_cmdline() -> List[str]:
    """Capture the command that launched this process."""
    return [sys.executable or "python"] + (sys.argv or [])


class PidFileLock:
    """Ensure only one process owns the named PID file."""

    def __init__(self, name: str, *, wait_seconds: float = 5.0, poll_interval: float = 0.1):
        self.path = Path(tempfile.gettempdir()) / f"{name}.pid.json"
        self.wait_seconds = wait_seconds
        self.poll_interval = poll_interval
        self.pid = os.getpid()
        self.cmdline = _current_cmdline()
        self.boot_time = _boot_signature()
        self._active = False
        self._atexit_registered = False

    def acquire(self) -> None:
        """Acquire the PID file, terminating matching owners if necessary."""
        deadline = time.monotonic() + self.wait_seconds
        while True:
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                owner = self._read_owner()
                if not owner:
                    self._cleanup_stale()
                    continue
                owner_pid = owner.get("pid")
                owner_boot = owner.get("boot_time", 0.0)
                owner_cmd = owner.get("cmdline", [])

                if owner_boot and owner_boot != self.boot_time:
                    # Different boot session: stale file.
                    self._cleanup_stale()
                    continue

                if not self._process_matches(owner_pid, owner_cmd):
                    self._cleanup_stale()
                    continue

                self._terminate(owner_pid)
                self._wait_for_exit(owner_pid, deadline)
                self._cleanup_stale()
                continue

            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "pid": self.pid,
                        "cmdline": self.cmdline,
                        "boot_time": self.boot_time,
                    },
                    handle,
                )
            self._active = True
            if not self._atexit_registered:
                atexit.register(self.release)
                self._atexit_registered = True
            return

    def release(self) -> None:
        """Release the PID file if we still own it."""
        if not self._active:
            return
        try:
            owner = self._read_owner()
            if owner and owner.get("pid") == self.pid:
                self.path.unlink(missing_ok=True)
        except Exception:
            pass
        finally:
            self._active = False

    def _cleanup_stale(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    def _read_owner(self) -> Optional[Dict[str, Any]]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _process_matches(self, pid: Optional[int], expected_cmd: List[str]) -> bool:
        if not pid or pid <= 0:
            return False
        try:
            proc = psutil.Process(pid)
        except psutil.Error:
            return False
        try:
            actual_cmd = proc.cmdline()
        except psutil.Error:
            actual_cmd = []
        if expected_cmd and actual_cmd:
            # Exact match is required to avoid terminating unrelated apps.
            if actual_cmd != expected_cmd:
                return False
        try:
            proc.status()
        except psutil.Error:
            return False
        return True

    def _terminate(self, pid: int) -> None:
        try:
            proc = psutil.Process(pid)
        except psutil.Error:
            return
        try:
            proc.terminate()
        except psutil.Error:
            try:
                proc.kill()
            except psutil.Error:
                pass

    def _wait_for_exit(self, pid: int, deadline: float) -> None:
        while time.monotonic() < deadline:
            try:
                proc = psutil.Process(pid)
                proc_status = proc.status()
            except psutil.Error:
                return
            if proc_status == psutil.STATUS_ZOMBIE:
                return
            time.sleep(self.poll_interval)
        raise SingleInstanceError(f"Another wkey-tray instance (PID {pid}) is still running.")
