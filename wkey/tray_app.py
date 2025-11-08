"""System tray launcher for whisper-keyboard."""
import os
import signal
import sys
import threading

from queue import Queue

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QIcon, QPainter, QPixmap, QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from pynput import keyboard as pynput_keyboard, mouse as pynput_mouse

from wkey.config import (
    SETTINGS_PATH,
    apply_settings,
    load_settings,
    save_settings,
)
from wkey.llm_correction import DEFAULT_PROMPT
from wkey.single_instance import PidFileLock, SingleInstanceError
from wkey.wkey import start_service, stop_service, refresh_configuration, set_error_handler, set_paused


def _build_default_icon():
    """Create a simple in-memory icon so we do not depend on external assets."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor("#3f51b5"))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(4, 4, 56, 56)
    painter.setPen(QColor("#ffffff"))
    font = QFont()
    font.setBold(True)
    font.setPointSize(22)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "W")
    painter.end()
    return QIcon(pixmap)


class SettingsDialog(QDialog):
    mousePracticeDetected = Signal(str)
    """Dialog for viewing basic info and editing settings."""

    def __init__(self, settings, save_callback, exit_callback, close_callback, parent=None):
        super().__init__(parent)
        self.exit_callback = exit_callback
        self.save_callback = save_callback
        self.close_callback = close_callback
        self.current_settings = settings.copy()
        self.listener = None
        self.mouse_listener = None
        self.pressed_keys = set()
        self.key_queue: Queue[str] = Queue()
        self.recent_keys = []
        self._close_callback_called = False
        self._close_callback_called = False

        self.setWindowTitle("wkey Settings")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setModal(True)
        self.resize(720, 420)  # roughly 1.6x wider than the default dialog size

        info = QLabel(
            "whisper-keyboard is running in the background.\n"
            "Update your API keys or hotkey below. Settings are stored at:\n"
            f"<code>{SETTINGS_PATH}</code>"
        )
        info.setWordWrap(True)
        info.setTextFormat(Qt.RichText)

        form = QFormLayout()

        self.groq_input = QLineEdit()
        self.groq_input.setEchoMode(QLineEdit.Password)
        form.addRow("Groq API key", self.groq_input)

        self.openai_input = QLineEdit()
        self.openai_input.setEchoMode(QLineEdit.Password)
        form.addRow("OpenAI API key", self.openai_input)

        self.backend_combo = QComboBox()
        self.backend_combo.addItems(["", "groq", "openai", "whisperx", "insanely-whisper"])
        form.addRow("Whisper backend", self.backend_combo)

        self.hotkey_input = QLineEdit()
        hotkey_row = QHBoxLayout()
        hotkey_row.addWidget(self.hotkey_input, 1)
        self.keyboard_enabled_checkbox = QCheckBox("Enable")
        hotkey_row.addWidget(self.keyboard_enabled_checkbox, 1)
        form.addRow("Keyboard shortcut", hotkey_row)

        self.capture_button = QPushButton("Capture hotkey")
        self.capture_button.setCheckable(True)
        self.capture_button.toggled.connect(self._toggle_capture)
        form.addRow("", self.capture_button)

        recent_keys_label = QLabel("Recent presses")
        recent_keys_label.setToolTip("Click an item to apply it as the new hotkey.")

        self.recent_keys_list = QListWidget()
        self.recent_keys_list.setMinimumHeight(100)
        self.recent_keys_list.itemClicked.connect(self._select_recent_key)
        recent_keys_container = QVBoxLayout()
        recent_keys_container.setSpacing(4)
        recent_keys_container.addWidget(recent_keys_label)
        instruction = QLabel("Click on an item to change the hotkey value.")
        instruction.setObjectName("recentKeysInstruction")
        instruction.setStyleSheet("#recentKeysInstruction { color: #666; font-size: 11px; }")
        recent_keys_container.addWidget(instruction)
        recent_keys_container.addWidget(self.recent_keys_list)
        recent_keys_widget = QWidget()
        recent_keys_widget.setLayout(recent_keys_container)
        form.addRow("", recent_keys_widget)

        self.mouse_button_combo = QComboBox()
        self.mouse_button_combo.addItem("Disabled", "")
        self.mouse_button_combo.addItem("Middle mouse", "middle")
        self.mouse_button_combo.addItem("Thumb button 1 (Mouse 4)", "x1")
        self.mouse_button_combo.addItem("Thumb button 2 (Mouse 5)", "x2")
        mouse_row = QHBoxLayout()
        mouse_row.addWidget(self.mouse_button_combo, 1)
        self.mouse_enabled_checkbox = QCheckBox("Enable")
        mouse_row.addWidget(self.mouse_enabled_checkbox, 1)
        form.addRow("Mouse trigger", mouse_row)

        self.mouse_practice_label = QLabel("Press a mouse button to preview")
        self.mouse_practice_label.setAlignment(Qt.AlignCenter)
        self.mouse_practice_label.setMinimumHeight(60)
        self.mouse_practice_label.setStyleSheet(
            "border: 1px dashed #888; border-radius: 6px; color: #333; font-size: 13px; padding: 8px;"
        )
        form.addRow("Mouse practice", self.mouse_practice_label)

        self.continuous_listen_checkbox = QCheckBox("Keep microphone active for faster start")
        self.continuous_listen_checkbox.setToolTip(
            "When enabled, wkey keeps the microphone stream open all the time for quicker dictation starts."
        )
        form.addRow("Continuous listening", self.continuous_listen_checkbox)

        self.llm_checkbox = QCheckBox("Enable LLM correction")
        self.llm_checkbox.toggled.connect(self._update_llm_controls)

        self.llm_provider_combo = QComboBox()
        self.llm_provider_combo.addItem("OpenAI (OPENAI_API_KEY)", "openai")
        self.llm_provider_combo.addItem("Groq (GROQ_API_KEY)", "groq")
        self.llm_provider_combo.currentIndexChanged.connect(lambda _: self._update_llm_controls())

        self.reset_prompt_button = QPushButton("Reset prompt")
        self.reset_prompt_button.clicked.connect(self._reset_llm_prompt)

        llm_row = QHBoxLayout()
        llm_row.addWidget(self.llm_checkbox)
        llm_row.addWidget(self.llm_provider_combo, 1)
        llm_row.addWidget(self.reset_prompt_button)
        form.addRow("LLM correction", llm_row)

        self.llm_prompt_input = QTextEdit()
        self.llm_prompt_input.setPlaceholderText("Optional: custom LLM instructions for post-processing.")
        self.llm_prompt_input.setFixedHeight(80)
        self.llm_prompt_input.setAcceptRichText(False)
        form.addRow("LLM prompt", self.llm_prompt_input)
        self._update_llm_controls()

        self.chinese_combo = QComboBox()
        self.chinese_combo.addItem("Disabled", "")
        conversions = [
            ("hk2s", "HK Traditional → Simplified"),
            ("s2hk", "Simplified → HK Traditional"),
            ("s2t", "Simplified → Traditional"),
            ("s2tw", "Simplified → Taiwan Traditional"),
            ("s2twp", "Simplified → Taiwan Traditional (phrases)"),
            ("t2hk", "Traditional → HK Traditional"),
            ("t2s", "Traditional → Simplified"),
            ("t2tw", "Traditional → Taiwan Traditional"),
            ("tw2s", "Taiwan Traditional → Simplified"),
            ("tw2sp", "Taiwan Traditional → Simplified (phrases)"),
        ]
        for code, label in conversions:
            self.chinese_combo.addItem(label, code)
        form.addRow("Chinese conversion", self.chinese_combo)

        button_row = QHBoxLayout()
        exit_button = QPushButton("Exit wkey")
        exit_button.clicked.connect(self._handle_exit_clicked)
        button_row.addWidget(exit_button)
        button_row.addStretch(1)
        ok_button = QPushButton("OK")
        ok_button.clicked.connect(self.accept)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(ok_button)
        button_row.addWidget(cancel_button)

        layout = QVBoxLayout()
        layout.addWidget(info)
        layout.addLayout(form)
        layout.addLayout(button_row)
        self.setLayout(layout)

        self.mousePracticeDetected.connect(self._apply_mouse_pad)

        self.key_timer = QTimer(self)
        self.key_timer.setInterval(150)
        self.key_timer.timeout.connect(self._drain_key_queue)
        self.key_timer.start()
        self._start_mouse_practice()

        self.load_from_settings(settings)

    def _collect_settings(self):
        hotkey_value = self.hotkey_input.text().strip()
        if not hotkey_value:
            hotkey_value = "ctrl_r" if self.keyboard_enabled_checkbox.isChecked() else ""
        return {
            "groq_api_key": self.groq_input.text().strip(),
            "openai_api_key": self.openai_input.text().strip(),
            "whisper_backend": self.backend_combo.currentText().strip(),
            "hotkey": hotkey_value,
            "mouse_button": self.mouse_button_combo.currentData() or "",
            "enable_keyboard_shortcut": self.keyboard_enabled_checkbox.isChecked(),
            "enable_mouse_shortcut": self.mouse_enabled_checkbox.isChecked(),
            "continuous_listen": self.continuous_listen_checkbox.isChecked(),
            "llm_correct": self.llm_checkbox.isChecked(),
            "llm_provider": self.llm_provider_combo.currentData(),
            "llm_prompt": self.llm_prompt_input.toPlainText().strip(),
            "chinese_conversion": self.chinese_combo.currentData() or "",
        }

    def load_from_settings(self, settings):
        self._close_callback_called = False
        self.current_settings = settings.copy()
        self.groq_input.setText(settings.get("groq_api_key", ""))
        self.openai_input.setText(settings.get("openai_api_key", ""))
        backend_value = settings.get("whisper_backend", "")
        index = self.backend_combo.findText(backend_value)
        self.backend_combo.setCurrentIndex(index if index >= 0 else 0)
        self.hotkey_input.setText(settings.get("hotkey", "ctrl_r"))
        self.keyboard_enabled_checkbox.setChecked(bool(settings.get("enable_keyboard_shortcut", True)))
        mouse_value = settings.get("mouse_button", "")
        idx = self.mouse_button_combo.findData(mouse_value)
        self.mouse_button_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.mouse_enabled_checkbox.setChecked(bool(settings.get("enable_mouse_shortcut", True)))
        self.continuous_listen_checkbox.setChecked(bool(settings.get("continuous_listen", True)))
        self.llm_checkbox.setChecked(bool(settings.get("llm_correct")))
        provider_value = settings.get("llm_provider", "openai")
        idx = self.llm_provider_combo.findData(provider_value)
        self.llm_provider_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.llm_prompt_input.setPlainText(settings.get("llm_prompt", "").strip())
        self._update_llm_controls()
        conversion_value = settings.get("chinese_conversion", "")
        idx = self.chinese_combo.findData(conversion_value)
        self.chinese_combo.setCurrentIndex(idx if idx >= 0 else 0)

    def accept(self):
        data = self._collect_settings()
        self.save_callback(data, persist=True)
        self._notify_closed()
        super().accept()

    def reject(self):
        self._notify_closed()
        super().reject()

    def _handle_exit_clicked(self):
        self.close()
        self.exit_callback()

    def _toggle_capture(self, checked):
        if checked:
            self.capture_button.setText("Stop capture")
            self._start_listener()
        else:
            self.capture_button.setText("Capture hotkey")
            self._stop_listener()

    def _start_listener(self):
        if self.listener and self.listener.running:
            return
        self.listener = pynput_keyboard.Listener(on_press=self._on_key_press, on_release=self._on_key_release)
        self.listener.start()

    def _stop_listener(self):
        if self.listener:
            self.listener.stop()
            self.listener = None
        self.pressed_keys.clear()

    def _start_mouse_practice(self):
        if self.mouse_listener and self.mouse_listener.running:
            return
        self.mouse_listener = pynput_mouse.Listener(on_click=self._on_mouse_practice)
        self.mouse_listener.start()

    def _stop_mouse_practice(self):
        if self.mouse_listener:
            self.mouse_listener.stop()
            self.mouse_listener = None

    def ensure_mouse_practice(self):
        self._start_mouse_practice()

    def stop_mouse_practice(self):
        self._stop_mouse_practice()

    def _on_key_press(self, key):
        if not hasattr(self, "pressed_keys"):
            self.pressed_keys = set()
        label = self._key_name(key)
        if label:
            self.pressed_keys.add(label)
            combo = self._format_combo(self.pressed_keys)
            self.key_queue.put(combo)

    def _on_key_release(self, key):
        if not hasattr(self, "pressed_keys"):
            return
        label = self._key_name(key)
        if label and label in self.pressed_keys:
            self.pressed_keys.remove(label)

    def _on_mouse_practice(self, x, y, button, pressed):
        if not pressed:
            return
        label = self._format_mouse_button(button)
        self._update_mouse_pad(label)

    @staticmethod
    def _key_name(key):
        if isinstance(key, pynput_keyboard.Key):
            return key.name
        if isinstance(key, pynput_keyboard.KeyCode) and key.char:
            return key.char.lower()
        return None

    @staticmethod
    def _format_combo(key_names):
        ordering = sorted(key_names, key=lambda k: (0, k) if len(k) > 1 else (1, k))
        return "+".join(ordering)

    @staticmethod
    def _format_mouse_button(button):
        mapping = {
            pynput_mouse.Button.left: "left",
            pynput_mouse.Button.right: "right",
            pynput_mouse.Button.middle: "middle",
            pynput_mouse.Button.x1: "x1 (mouse 4)",
            pynput_mouse.Button.x2: "x2 (mouse 5)",
        }
        return mapping.get(button, str(button))

    def _update_mouse_pad(self, label: str):
        self.mousePracticeDetected.emit(f"Detected: {label}")

    def _apply_mouse_pad(self, text: str):
        self.mouse_practice_label.setText(text)

    def _reset_llm_prompt(self):
        self.llm_prompt_input.setPlainText(DEFAULT_PROMPT.strip())

    def _update_llm_controls(self, enabled=None):
        if enabled is None:
            enabled = self.llm_checkbox.isChecked()
        self.llm_prompt_input.setEnabled(enabled)
        self.reset_prompt_button.setEnabled(enabled)
        self.llm_provider_combo.setEnabled(enabled)

    def _drain_key_queue(self):
        updated = False
        while not self.key_queue.empty():
            label = self.key_queue.get()
            if label in self.recent_keys:
                self.recent_keys.remove(label)
            self.recent_keys.insert(0, label)
            self.recent_keys = self.recent_keys[:12]
            updated = True
        if updated:
            self.recent_keys_list.clear()
            for label in self.recent_keys:
                self.recent_keys_list.addItem(QListWidgetItem(label))

    def _select_recent_key(self, item: QListWidgetItem):
        self.hotkey_input.setText(item.text())
        self.capture_button.setChecked(False)

    def _notify_closed(self):
        if not self._close_callback_called and self.close_callback:
            self._close_callback_called = True
            self.close_callback()

    def closeEvent(self, event):
        self.capture_button.setChecked(False)
        self._stop_listener()
        self.stop_mouse_practice()
        self.key_timer.stop()
        self._notify_closed()
        super().closeEvent(event)


class TrayController:
    """Owns the background service thread and tray UI."""

    def __init__(self, app: QApplication, sigint_event: threading.Event, instance_lock: 'PidFileLock'):
        self.app = app
        self.sigint_event = sigint_event
        self.exiting = False
        self.instance_lock = instance_lock
        self.stop_event, self.worker_thread = start_service()

        self.tray_icon = QSystemTrayIcon(_build_default_icon(), self.app)
        self.tray_icon.setToolTip("wkey is active – hold your hotkey to dictate")
        self.tray_icon.activated.connect(self._handle_activation)

        self.settings, self.has_user_overrides = load_settings()
        if self.has_user_overrides:
            apply_settings(self.settings, clear_missing=True)

        self.auto_paused = False
        self.settings_dialog = SettingsDialog(
            self._dialog_settings(),
            self._handle_settings_update,
            self.exit_app,
            self._on_settings_closed,
        )
        self.settings_dialog.finished.connect(lambda _: self._on_settings_closed())
        set_error_handler(self.handle_service_error)

        menu = QMenu()
        settings_action = QAction("Settings", menu)
        settings_action.triggered.connect(self.show_settings)
        self.paused_action = QAction("Pause dictation", menu, checkable=True)
        self.paused_action.triggered.connect(self.toggle_pause)
        exit_action = QAction("Exit", menu)
        exit_action.triggered.connect(self.exit_app)
        menu.addAction(settings_action)
        menu.addAction(self.paused_action)
        menu.addSeparator()
        menu.addAction(exit_action)
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.show()

        self._sigint_timer = QTimer(self.app)
        self._sigint_timer.setInterval(200)
        self._sigint_timer.timeout.connect(self._check_sigint)
        self._sigint_timer.start()

    def _handle_activation(self, reason):
        if reason in {QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick}:
            self.show_settings()

    def show_settings(self):
        self.settings_dialog.load_from_settings(self._dialog_settings())
        self.settings_dialog.ensure_mouse_practice()
        if not self.paused_action.isChecked():
            self.auto_paused = True
            self.paused_action.setChecked(True)
            self.toggle_pause(True, suppress_action_toggle=True)
        else:
            self.auto_paused = False
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def _handle_settings_update(self, new_settings, persist):
        self.settings.update(new_settings)
        if persist:
            save_settings(self.settings)
            self.has_user_overrides = True
        apply_settings(self.settings, clear_missing=True)
        refresh_configuration(self.settings, clear_missing=True)

    def _check_sigint(self):
        if self.sigint_event.is_set():
            self.exit_app()

    def exit_app(self):
        if self.exiting:
            return
        self.exiting = True
        self.tray_icon.hide()
        if hasattr(self, "settings_dialog"):
            self.settings_dialog.stop_mouse_practice()
        set_error_handler(None)
        set_paused(False)
        stop_service(self.stop_event, self.worker_thread)
        if self.instance_lock:
            self.instance_lock.release()
        self.app.quit()

    def handle_service_error(self, message: str):
        def show():
            if not self.exiting:
                QMessageBox.critical(None, "wkey error", message)
        QTimer.singleShot(0, show)

    def toggle_pause(self, checked, suppress_action_toggle=False):
        set_paused(checked)
        if not suppress_action_toggle:
            self.paused_action.setChecked(checked)

    def _on_settings_closed(self):
        if self.auto_paused:
            self.auto_paused = False
            self.paused_action.setChecked(False)
            self.toggle_pause(False, suppress_action_toggle=True)

    def _dialog_settings(self):
        values = self.settings.copy()
        values.setdefault("enable_keyboard_shortcut", True)
        values.setdefault("enable_mouse_shortcut", True)
        if not self.has_user_overrides:
            values["groq_api_key"] = os.environ.get("GROQ_API_KEY", values.get("groq_api_key", ""))
            values["openai_api_key"] = os.environ.get("OPENAI_API_KEY", values.get("openai_api_key", ""))
            values["whisper_backend"] = os.environ.get("WHISPER_BACKEND", values.get("whisper_backend", ""))
            values["hotkey"] = os.environ.get("WKEY", values.get("hotkey", "ctrl_r"))
            values["mouse_button"] = os.environ.get("WKEY_MOUSE_BUTTON", values.get("mouse_button", ""))
            kb_env = os.environ.get("WKEY_KEYBOARD_ENABLED")
            if kb_env is not None:
                values["enable_keyboard_shortcut"] = kb_env.lower() in ("1", "true", "yes", "on")
            else:
                values["enable_keyboard_shortcut"] = values.get("enable_keyboard_shortcut", True)
            mouse_env = os.environ.get("WKEY_MOUSE_ENABLED")
            if mouse_env is not None:
                values["enable_mouse_shortcut"] = mouse_env.lower() in ("1", "true", "yes", "on")
            else:
                values["enable_mouse_shortcut"] = values.get("enable_mouse_shortcut", True)
            llm_env = os.environ.get("LLM_CORRECT")
            if llm_env is not None:
                values["llm_correct"] = llm_env.lower() in ("1", "true", "yes", "on")
            provider = os.environ.get("LLM_CORRECT_PROVIDER", values.get("llm_provider", "openai"))
            if provider not in {"openai", "groq"}:
                provider = "openai"
            values["llm_provider"] = provider
            values["llm_prompt"] = os.environ.get("LLM_CORRECT_PROMPT", values.get("llm_prompt", ""))
            values["chinese_conversion"] = os.environ.get("CHINESE_CONVERSION", values.get("chinese_conversion", ""))
        return values


def main():
    try:
        instance_lock = PidFileLock("wkey-tray")
        instance_lock.acquire()
    except SingleInstanceError as exc:
        print(exc)
        return 0

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    sigint_event = threading.Event()
    controller = TrayController(app, sigint_event, instance_lock)

    def handle_sigint(signum, frame):
        sigint_event.set()

    signal.signal(signal.SIGINT, handle_sigint)
    try:
        return app.exec()
    finally:
        controller.exit_app()


if __name__ == "__main__":
    sys.exit(main())
