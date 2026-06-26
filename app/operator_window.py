from PySide6.QtWidgets import (
    QWidget,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QComboBox,
    QMessageBox,
)

from audience_window import AudienceWindow
from conference_view import ConferenceView
from draft_view import DraftView
from caption_worker import CaptionWorker
from audio_engine import AudioEngine
from whisper_engine import cuda_available


class CaptionBoxWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.worker = None
        self.audio_devices = []

        self.audience_window = AudienceWindow(font_px=34)
        self.audience_window.show()

        self.setWindowTitle("CaptionBox AV")
        self.resize(1320, 840)
        self.setStyleSheet("background-color: #202020; color: white;")

        self.title = QLabel("CaptionBox AV")
        self.title.setStyleSheet("font-size: 32px; font-weight: 700;")

        self.status_label = QLabel("Gotowy. Wybierz wejście audio i naciśnij START.")
        self.status_label.setStyleSheet("font-size: 18px; color: #aaa;")

        self.audio_label = QLabel("Źródło audio:")
        self.audio_label.setStyleSheet("font-size: 16px;")
        self.audio_combo = QComboBox()
        self.audio_combo.setStyleSheet("font-size: 16px; padding: 8px;")

        self.refresh_button = QPushButton("Odśwież")
        self.refresh_button.setStyleSheet("font-size: 15px; padding: 8px;")
        self.refresh_button.clicked.connect(self.refresh_audio_devices)

        self.compute_label = QLabel("Obliczenia:")
        self.compute_label.setStyleSheet("font-size: 16px;")
        self.compute_combo = QComboBox()
        self.compute_combo.setStyleSheet("font-size: 16px; padding: 8px;")
        self.compute_combo.addItem("CPU - tryb awaryjny", "cpu")
        if cuda_available():
            self.compute_combo.addItem("GPU / CUDA - zalecane", "cuda")
            self.compute_combo.setCurrentIndex(self.compute_combo.findData("cuda"))
        else:
            self.compute_combo.addItem("GPU / CUDA - niewykryte", "cuda_unavailable")
            idx = self.compute_combo.findData("cuda_unavailable")
            item = self.compute_combo.model().item(idx)
            if item:
                item.setEnabled(False)

        self.model_label = QLabel("Model:")
        self.model_label.setStyleSheet("font-size: 16px;")
        self.model_combo = QComboBox()
        self.model_combo.setStyleSheet("font-size: 16px; padding: 8px;")
        self.model_combo.addItem("medium - zalecane RTX 3070", "medium")
        self.model_combo.addItem("small - szybszy / CPU", "small")
        self.model_combo.addItem("base - awaryjny CPU", "base")
        self.model_combo.addItem("large-v3 - dokładniejszy / mocny RTX", "large-v3")

        self.font_label = QLabel("Czcionka publiczności:")
        self.font_label.setStyleSheet("font-size: 16px;")
        self.font_combo = QComboBox()
        self.font_combo.setStyleSheet("font-size: 16px; padding: 8px;")
        for size in [28, 30, 32, 34, 36, 40, 44, 48]:
            self.font_combo.addItem(f"{size} px", size)
        self.font_combo.setCurrentIndex(self.font_combo.findData(34))
        self.font_combo.currentIndexChanged.connect(self.apply_font_size)

        self.approved_title = QLabel("Publiczność / zatwierdzone napisy")
        self.approved_title.setStyleSheet("font-size: 17px; color: #bbb; font-weight: 600;")
        self.public_preview = ConferenceView(font_px=34, margin_px=34)

        self.draft_title = QLabel("Robocze rozpoznanie operatora / nie idzie na ekran publiczności")
        self.draft_title.setStyleSheet("font-size: 16px; color: #e2d99a; font-weight: 600;")
        self.draft_view = DraftView()

        self.hint_label = QLabel(
            "Okno publiczności można przenieść na TV. F11 = pełny ekran, ESC = wyjście z pełnego ekranu."
        )
        self.hint_label.setStyleSheet("font-size: 15px; color: #aaa;")

        self.start_button = QPushButton("START")
        self.start_button.setStyleSheet("font-size: 24px; padding: 18px;")
        self.start_button.clicked.connect(self.start_captioning)

        self.stop_button = QPushButton("STOP")
        self.stop_button.setStyleSheet("font-size: 24px; padding: 18px;")
        self.stop_button.clicked.connect(self.stop_captioning)
        self.stop_button.setEnabled(False)

        self.fullscreen_button = QPushButton("PUBLICZNOŚĆ FULLSCREEN")
        self.fullscreen_button.setStyleSheet("font-size: 18px; padding: 16px;")
        self.fullscreen_button.clicked.connect(self.toggle_audience_fullscreen)

        self.refresh_audio_devices()
        self._build_layout()

    def _build_layout(self):
        audio_layout = QHBoxLayout()
        audio_layout.addWidget(self.audio_label)
        audio_layout.addWidget(self.audio_combo, stretch=1)
        audio_layout.addWidget(self.refresh_button)

        settings_layout = QHBoxLayout()
        settings_layout.addWidget(self.compute_label)
        settings_layout.addWidget(self.compute_combo, stretch=2)
        settings_layout.addWidget(self.model_label)
        settings_layout.addWidget(self.model_combo, stretch=2)
        settings_layout.addWidget(self.font_label)
        settings_layout.addWidget(self.font_combo, stretch=1)

        buttons = QHBoxLayout()
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)
        buttons.addWidget(self.fullscreen_button)

        layout = QVBoxLayout()
        layout.addWidget(self.title)
        layout.addWidget(self.status_label)
        layout.addLayout(audio_layout)
        layout.addLayout(settings_layout)
        layout.addWidget(self.approved_title)
        layout.addWidget(self.public_preview, stretch=1)
        layout.addWidget(self.draft_title)
        layout.addWidget(self.draft_view)
        layout.addWidget(self.hint_label)
        layout.addLayout(buttons)
        self.setLayout(layout)

    def refresh_audio_devices(self):
        self.audio_combo.clear()
        try:
            self.audio_devices = AudioEngine.list_input_devices()
        except Exception as exc:
            self.audio_devices = []
            self.audio_combo.addItem(f"Nie udało się odczytać wejść audio: {exc}", None)
            return

        if not self.audio_devices:
            self.audio_combo.addItem("Brak wykrytych wejść audio", None)
            return

        for dev in self.audio_devices:
            label = f'{dev["name"]}  |  wejścia: {dev["max_input_channels"]}  |  ID: {dev["id"]}'
            self.audio_combo.addItem(label, dev)

    def apply_font_size(self):
        size = self.font_combo.currentData() or 34
        self.public_preview.set_font_px(size)
        self.audience_window.set_font_px(size)

    def start_captioning(self):
        selected_audio = self.audio_combo.currentData()
        if selected_audio is None:
            QMessageBox.critical(self, "CaptionBox AV", "Nie wybrano poprawnego wejścia audio.")
            return

        compute_device = self.compute_combo.currentData() or "cpu"
        if compute_device == "cuda_unavailable":
            compute_device = "cpu"

        model_size = self.model_combo.currentData() or "medium"
        channels = min(2, int(selected_audio.get("max_input_channels", 1)))

        self.public_preview.clear()
        self.audience_window.clear()
        self.draft_view.set_draft("")
        self.status_label.setText("Ładowanie modelu...")

        self.worker = CaptionWorker(
            audio_device_id=selected_audio["id"],
            audio_device_name=selected_audio["name"],
            audio_channels=channels,
            compute_device=compute_device,
            model_size=model_size,
        )
        self.worker.state_changed.connect(self.update_public_state)
        self.worker.draft_changed.connect(self.draft_view.set_draft)
        self.worker.status.connect(self.status_label.setText)
        self.worker.error.connect(self.show_error)
        self.worker.finished.connect(self.worker_finished)
        self.worker.start()

        self._set_running_ui(True)

    def stop_captioning(self):
        if self.worker:
            self.worker.stop()
            self.worker.wait()
            self.worker = None
        self._set_running_ui(False)

    def worker_finished(self):
        self.worker = None
        self._set_running_ui(False)

    def _set_running_ui(self, running):
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.audio_combo.setEnabled(not running)
        self.refresh_button.setEnabled(not running)
        self.compute_combo.setEnabled(not running)
        self.model_combo.setEnabled(not running)

    def update_public_state(self, history, current):
        self.public_preview.set_state(history, current)
        self.audience_window.set_state(history, current)

    def show_error(self, text):
        self.status_label.setText(text)
        QMessageBox.critical(self, "CaptionBox AV", text)

    def toggle_audience_fullscreen(self):
        self.audience_window.toggle_fullscreen()

    def closeEvent(self, event):
        self.stop_captioning()
        self.audience_window.close()
        event.accept()
