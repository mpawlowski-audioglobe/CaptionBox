import sys
from PySide6.QtWidgets import QApplication
from operator_window import CaptionBoxWindow


app = QApplication(sys.argv)
window = CaptionBoxWindow()
window.show()
sys.exit(app.exec())
