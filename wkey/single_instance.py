"""PID-file based single-instance helper for wkey."""
from __future__ import annotations

import atexit
import importlib.util
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


def _resolve_module_origin(module_name: str) -> Optional[str]:
    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, AttributeError, ValueError):
        return None
    if spec and getattr(spec, "origin", None):
        try:
            return os.path.abspath(spec.origin)
        except OSError:
            return None
    return None


def _canonical_entry(cmd: List[str]) -> Optional[str]:
    if len(cmd) < 2:
        return None
    entry = cmd[1]
    if entry == "-m" and len(cmd) >= 3:
        module = cmd[2]
        origin = _resolve_module_origin(module)
        if origin:
            try:
                return os.path.abspath(origin)
            except OSError:
                return origin
        return module
    if entry.endswith(".py"):
        try:
            return os.path.abspath(entry)
        except OSError:
            return entry
    return None


def _commands_equivalent(expected: List[str], actual: List[str]) -> bool:
    if expected == actual:
        return True
    if not expected or not actual:
        return False
    expected_exe = os.path.abspath(expected[0]) if expected[0] else ""
    actual_exe = os.path.abspath(actual[0]) if actual[0] else ""
    if expected_exe != actual_exe:
        return False
    expected_entry = _canonical_entry(expected)
    actual_entry = _canonical_entry(actual)
    if expected_entry and actual_entry and expected_entry == actual_entry:
        return True
    return False


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

    def _debug(self, message: str) -> None:
        print(f"[PidFileLock:{self.path.name}] {message}")

    def acquire(self) -> None:
        """Acquire the PID file, terminating matching owners if necessary."""
        deadline = time.monotonic() + self.wait_seconds
        while True:
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                self._debug("PID file already exists; reading owner metadata.")
                owner = self._read_owner()
                if not owner:
                    self._debug("PID file empty or unreadable. Removing stale file.")
                    self._cleanup_stale()
                    continue
                owner_pid = owner.get("pid")
                owner_boot = owner.get("boot_time", 0.0)
                owner_cmd = owner.get("cmdline", [])
                self._debug(f"Owner record -> pid={owner_pid}, boot={owner_boot}, cmd={owner_cmd}")

                if owner_boot and not self._same_boot(owner_boot, self.boot_time):
                    # Different boot session: stale file.
                    self._debug(
                        f"Boot signature mismatch (owner={owner_boot}, current={self.boot_time}). Removing file."
                    )
                    self._cleanup_stale()
                    continue

                if not self._process_matches(owner_pid, owner_cmd):
                    self._debug("Owner process no longer matches expected command. Removing file.")
                    self._cleanup_stale()
                    continue

                self._terminate(owner_pid)
                self._wait_for_exit(owner_pid, deadline)
                self._cleanup_stale()
                continue

            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                self._debug(f"Writing PID file for pid={self.pid}, cmd={self.cmdline}.")
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
                self._debug("Releasing PID file.")
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
            contents = self.path.read_text(encoding="utf-8")
            self._debug(f"Read PID file contents: {contents}")
            return json.loads(contents)
        except Exception as exc:
            self._debug(f"Failed to read PID file: {exc}")
            return None

    def _process_matches(self, pid: Optional[int], expected_cmd: List[str]) -> bool:
        if not pid or pid <= 0:
            self._debug(f"Invalid PID recorded: {pid}")
            return False
        try:
            proc = psutil.Process(pid)
        except psutil.Error as exc:
            self._debug(f"Process lookup failed for PID {pid}: {exc}")
            return False
        try:
            actual_cmd = proc.cmdline()
        except psutil.Error:
            actual_cmd = []
        self._debug(f"Comparing owner command {expected_cmd} with running command {actual_cmd}")
        if expected_cmd and actual_cmd:
            # Accept equivalent invocations (module vs script path)
            if not _commands_equivalent(expected_cmd, actual_cmd):
                self._debug("Command mismatch detected.")
                return False
        try:
            status = proc.status()
            self._debug(f"Process status for PID {pid}: {status}")
        except psutil.Error as exc:
            self._debug(f"Failed reading status for PID {pid}: {exc}")
            return False
        return True

    @staticmethod
    def _same_boot(owner: float, current: float, tolerance: float = 1.0) -> bool:
        """Boot times are equal within a small tolerance to handle float precision."""
        return abs(owner - current) <= tolerance

    def _terminate(self, pid: int) -> None:
        self._debug(f"Attempting to terminate PID {pid}.")
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
            self._debug(f"Waiting for PID {pid} to exit; status={proc_status}")
            if proc_status == psutil.STATUS_ZOMBIE:
                return
            time.sleep(self.poll_interval)
        raise SingleInstanceError(f"Another wkey-tray instance (PID {pid}) is still running.")
