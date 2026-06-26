from PySide6.QtWidgets import QLabel


class DraftView(QLabel):
    def __init__(self):
        super().__init__("Robocze rozpoznanie pojawi się tutaj.")
        self.setWordWrap(True)
        self.setMinimumHeight(74)
        self.setStyleSheet(
            """
            QLabel {
                background-color: #161616;
                color: #f0e8a8;
                border: 1px solid #333;
                border-radius: 10px;
                padding: 14px 22px;
                font-size: 22px;
            }
            """
        )

    def set_draft(self, text):
        text = (text or "").strip()
        self.setText(text if text else "Robocze rozpoznanie pojawi się tutaj.")
