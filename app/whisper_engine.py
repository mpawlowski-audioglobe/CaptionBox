import numpy as np

try:
    from cuda_runtime import prepare_cuda_paths
except ImportError:
    from app.cuda_runtime import prepare_cuda_paths

prepare_cuda_paths()

from faster_whisper import WhisperModel


def cuda_available():
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception as exc:
        print(f"CUDA check failed: {exc}")
        return False


class WhisperEngine:
    def __init__(self, model_size="medium", language="pl", device="cpu"):
        self.model_size = model_size
        self.language = language
        self.device = device if device in ("cpu", "cuda") else "cpu"

        if self.device == "cuda" and not cuda_available():
            print("CUDA unavailable. Falling back to CPU.")
            self.device = "cpu"

        self.model = self._load_model()
        print(f"Whisper ready: model={self.model_size}, device={self.device}")

    def _load_model(self):
        if self.device == "cuda":
            try:
                print(f"Loading Whisper: {self.model_size} | cuda | float16")
                return WhisperModel(self.model_size, device="cuda", compute_type="float16")
            except Exception as exc:
                print(f"CUDA load failed: {exc}")
                print("Falling back to CPU.")
                self.device = "cpu"

        print(f"Loading Whisper: {self.model_size} | cpu | int8")
        return WhisperModel(self.model_size, device="cpu", compute_type="int8")

    def transcribe_audio(self, samples, sample_rate):
        if samples is None or len(samples) == 0:
            return ""

        audio = np.asarray(samples, dtype=np.float32)
        if audio.ndim == 2:
            mono = audio.mean(axis=1)
        else:
            mono = audio

        mono = self._resample_to_16k(mono, sample_rate)
        if len(mono) == 0:
            return ""

        mono = np.clip(mono, -1.0, 1.0).astype(np.float32)

        segments, info = self.model.transcribe(
            mono,
            language=self.language,
            task="transcribe",
            beam_size=1,
            best_of=1,
            temperature=0.0,
            vad_filter=False,
            condition_on_previous_text=False,
            no_speech_threshold=0.65,
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
        )

        parts = []
        for segment in segments:
            text = (segment.text or "").strip()
            if text:
                parts.append(text)
        return " ".join(parts).strip()

    def _resample_to_16k(self, audio, original_rate):
        target_rate = 16000
        original_rate = int(original_rate or target_rate)
        audio = np.asarray(audio, dtype=np.float32)

        if original_rate == target_rate:
            return audio.astype(np.float32)

        if len(audio) == 0:
            return np.array([], dtype=np.float32)

        duration = len(audio) / float(original_rate)
        new_length = int(duration * target_rate)
        if new_length <= 0:
            return np.array([], dtype=np.float32)

        old_times = np.linspace(0, duration, num=len(audio), endpoint=False)
        new_times = np.linspace(0, duration, num=new_length, endpoint=False)
        return np.interp(new_times, old_times, audio).astype(np.float32)
