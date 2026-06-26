import time
import traceback

from PySide6.QtCore import QThread, Signal

from audio_buffer import AudioBuffer
from audio_engine import AudioEngine
from whisper_engine import WhisperEngine
from caption_engine import CaptionEngine


SAMPLE_RATE = 44100
DEFAULT_CHANNELS = 2


class CaptionWorker(QThread):
    state_changed = Signal(list, str)
    draft_changed = Signal(str)
    status = Signal(str)
    metrics_changed = Signal(float, str)
    error = Signal(str)

    def __init__(
        self,
        audio_device_id=None,
        audio_device_name=None,
        audio_channels=DEFAULT_CHANNELS,
        compute_device="cpu",
        model_size="medium",
    ):
        super().__init__()
        self.running = False
        self.compute_device = compute_device
        self.model_size = model_size
        self.audio_device_id = audio_device_id
        self.audio_device_name = audio_device_name
        self.audio_channels = max(1, min(int(audio_channels or DEFAULT_CHANNELS), DEFAULT_CHANNELS))

        self.audio_buffer = None
        self.audio_engine = None
        self.whisper_engine = None
        self.caption_engine = None

    def _build_engines(self):
        self.audio_buffer = AudioBuffer(
            sample_rate=SAMPLE_RATE,
            channels=self.audio_channels,
            max_seconds=24,
        )

        self.audio_engine = AudioEngine(
            audio_buffer=self.audio_buffer,
            device_id=self.audio_device_id,
            device_name=self.audio_device_name,
            sample_rate=SAMPLE_RATE,
            channels=self.audio_channels,
        )

        self.whisper_engine = WhisperEngine(
            model_size=self.model_size,
            language="pl",
            device=self.compute_device,
        )

        if self.compute_device == "cuda" and self.whisper_engine.device == "cpu":
            self.status.emit("GPU/CUDA niedostępne - przełączono automatycznie na CPU.")

        # Word Stabilizer v2.0: word-based LCP, stronger duplicate handling, pause finalization.
        self.caption_engine = CaptionEngine(
            audio_buffer=self.audio_buffer,
            whisper_engine=self.whisper_engine,
            sample_rate=SAMPLE_RATE,
            context_seconds=9.0,
            recent_rms_seconds=0.55,
            silence_threshold=0.0035,
            process_interval_seconds=0.58,
            pause_commit_seconds=0.95,
            max_history_blocks=20,
            max_current_words=72,
            max_current_chars=560,
            stable_repetitions_required=2,
            unstable_tail_words=1,
        )

    def run(self):
        self.running = True
        try:
            self.status.emit("Ładowanie silników...")
            self._build_engines()

            self.audio_engine.start()
            self.status.emit("LIVE | słucham")

            while self.running:
                time.sleep(0.05)
                state = self.caption_engine.process_once()
                if state is None:
                    continue
                self.state_changed.emit(state.history, state.current)
                self.draft_changed.emit(state.draft)
                self.status.emit(f"LIVE {state.note} | RMS: {state.rms:.4f}")
                self.metrics_changed.emit(float(state.rms), str(state.note))

        except Exception as exc:
            details = traceback.format_exc()
            print(details)
            self.error.emit(f"Błąd uruchomienia: {exc}")
        finally:
            if self.audio_engine:
                self.audio_engine.stop()
            self.status.emit("Zatrzymano.")

    def stop(self):
        self.running = False
