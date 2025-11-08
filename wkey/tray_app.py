"""System tray launcher for whisper-keyboard."""
import signal
import sys
import threading

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QIcon, QPainter, QPixmap, QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QMenu,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QHBoxLayout,
)

from wkey.wkey import start_service, stop_service


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


class AboutDialog(QDialog):
    """Small dialog that shows information plus close/exit buttons."""

    def __init__(self, exit_callback, parent=None):
        super().__init__(parent)
        self.exit_callback = exit_callback
        self.setWindowTitle("About whisper-keyboard")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setModal(True)

        label = QLabel(
            "whisper-keyboard is running in the background.\n"
            "Hold the configured hotkey to dictate text anywhere."
        )
        label.setWordWrap(True)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)

        exit_button = QPushButton("Exit wkey")
        exit_button.clicked.connect(self._handle_exit_clicked)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(close_button)
        button_row.addWidget(exit_button)

        layout = QVBoxLayout()
        layout.addWidget(label)
        layout.addLayout(button_row)
        self.setLayout(layout)

    def _handle_exit_clicked(self):
        self.close()
        self.exit_callback()


class TrayController:
    """Owns the background service thread and tray UI."""

    def __init__(self, app: QApplication, sigint_event: threading.Event):
        self.app = app
        self.sigint_event = sigint_event
        self.exiting = False
        self.stop_event, self.worker_thread = start_service()

        self.tray_icon = QSystemTrayIcon(_build_default_icon(), self.app)
        self.tray_icon.setToolTip("wkey is active – hold your hotkey to dictate")
        self.tray_icon.activated.connect(self._handle_activation)

        self.about_dialog = AboutDialog(self.exit_app)

        menu = QMenu()
        about_action = QAction("About wkey", menu)
        about_action.triggered.connect(self.show_about)
        exit_action = QAction("Exit", menu)
        exit_action.triggered.connect(self.exit_app)
        menu.addAction(about_action)
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
            self.show_about()

    def show_about(self):
        self.about_dialog.show()
        self.about_dialog.raise_()
        self.about_dialog.activateWindow()

    def _check_sigint(self):
        if self.sigint_event.is_set():
            self.exit_app()

    def exit_app(self):
        if self.exiting:
            return
        self.exiting = True
        self.tray_icon.hide()
        stop_service(self.stop_event, self.worker_thread)
        self.app.quit()


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    sigint_event = threading.Event()
    controller = TrayController(app, sigint_event)

    def handle_sigint(signum, frame):
        sigint_event.set()

    signal.signal(signal.SIGINT, handle_sigint)
    try:
        return app.exec()
    finally:
        controller.exit_app()


if __name__ == "__main__":
    sys.exit(main())
