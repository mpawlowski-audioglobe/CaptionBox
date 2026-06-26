from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QWidget


class ConferenceView(QWidget):
    """Conference renderer: history flows up, current utterance is anchored at bottom."""

    def __init__(self, font_px=34, margin_px=54, parent=None):
        super().__init__(parent)
        self.history = []
        self.current = ""
        self.placeholder = "Napisy pojawią się tutaj."
        self.font_px = int(font_px)
        self.margin_px = int(margin_px)
        self.setMinimumHeight(260)
        self.setStyleSheet("background-color: black;")

    def set_font_px(self, value):
        self.font_px = int(value)
        self.update()

    def set_state(self, history, current):
        self.history = list(history or [])
        self.current = current or ""
        self.update()

    def clear(self):
        self.history = []
        self.current = ""
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#000000"))
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        width = self.width()
        height = self.height()
        margin = self.margin_px
        max_width = max(160, width - margin * 2)
        x = margin
        bottom = height - margin

        if not self.history and not self.current:
            self._draw_text_block(
                painter,
                self.placeholder,
                x,
                margin,
                max_width,
                self.font_px,
                QColor("#5d6368"),
                False,
            )
            painter.end()
            return

        blocks = []
        for text in self.history:
            cleaned = (text or "").strip()
            if cleaned:
                blocks.append(("history", cleaned))
        if self.current.strip():
            blocks.append(("current", self.current.strip()))

        y = bottom
        history_age = 0

        # Draw from bottom to top. Blocks above the top are naturally clipped.
        for kind, text in reversed(blocks):
            if kind == "current":
                font_size = self.font_px
                color = QColor("#ffffff")
                bold = True
                gap = int(self.font_px * 0.90)
            else:
                font_size = max(20, self.font_px - 4)
                palette = ["#d6d6d6", "#b8bdc0", "#969da1", "#737b80", "#555d62", "#3f464a"]
                color = QColor(palette[min(history_age, len(palette) - 1)])
                bold = False
                gap = int(self.font_px * 0.65)
                history_age += 1

            block_height = self._measure_text_height(painter, text, max_width, font_size, bold)
            y -= block_height

            if y + block_height >= 0 and y <= height:
                self._draw_text_block(painter, text, x, y, max_width, font_size, color, bold)

            y -= gap

        painter.end()

    def _font(self, font_size, bold):
        font = QFont("Arial")
        font.setPixelSize(int(font_size))
        font.setWeight(QFont.DemiBold if bold else QFont.Normal)
        return font

    def _measure_text_height(self, painter, text, max_width, font_size, bold):
        painter.setFont(self._font(font_size, bold))
        rect = painter.boundingRect(
            0,
            0,
            int(max_width),
            10000,
            Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop,
            text,
        )
        return max(rect.height() + 8, int(font_size * 1.35))

    def _draw_text_block(self, painter, text, x, y, max_width, font_size, color, bold):
        painter.setPen(color)
        painter.setFont(self._font(font_size, bold))
        rect_height = self._measure_text_height(painter, text, max_width, font_size, bold)
        painter.drawText(
            int(x),
            int(y),
            int(max_width),
            int(rect_height),
            Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop,
            text,
        )
