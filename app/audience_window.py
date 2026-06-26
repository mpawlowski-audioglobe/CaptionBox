from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout

from conference_view import ConferenceView


class AudienceWindow(QWidget):
    def __init__(self, font_px=34):
        super().__init__()
        self.fullscreen = False
        self.setWindowTitle("CaptionBox AV - Publiczność")
        self.resize(1400, 800)
        self.setStyleSheet("background-color: black;")

        self.view = ConferenceView(font_px=font_px, margin_px=60)
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.setLayout(layout)

    def set_font_px(self, value):
        self.view.set_font_px(value)

    def set_state(self, history, current):
        self.view.set_state(history, current)

    def clear(self):
        self.view.clear()

    def toggle_fullscreen(self):
        if self.fullscreen:
            self.showNormal()
            self.fullscreen = False
        else:
            self.showFullScreen()
            self.fullscreen = True

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_F11:
            self.toggle_fullscreen()
        elif event.key() == Qt.Key_Escape and self.fullscreen:
            self.toggle_fullscreen()
        else:
            super().keyPressEvent(event)
