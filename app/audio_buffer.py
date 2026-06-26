import threading
import numpy as np


class AudioBuffer:
    def __init__(self, sample_rate=44100, channels=2, max_seconds=20):
        self.sample_rate = int(sample_rate)
        self.channels = int(max(1, channels))
        self.max_samples = int(self.sample_rate * float(max_seconds))
        self._buffer = np.zeros((0, self.channels), dtype=np.float32)
        self._lock = threading.Lock()

    def add(self, samples):
        if samples is None or len(samples) == 0:
            return

        arr = np.asarray(samples, dtype=np.float32)
        if arr.ndim == 1:
            arr = arr.reshape(-1, 1)

        if arr.shape[1] != self.channels:
            if arr.shape[1] > self.channels:
                arr = arr[:, : self.channels]
            else:
                pad = np.zeros((arr.shape[0], self.channels - arr.shape[1]), dtype=np.float32)
                arr = np.concatenate([arr, pad], axis=1)

        with self._lock:
            self._buffer = np.concatenate([self._buffer, arr], axis=0)
            if len(self._buffer) > self.max_samples:
                self._buffer = self._buffer[-self.max_samples :]

    def get_last_seconds(self, seconds):
        count = int(self.sample_rate * float(seconds))
        with self._lock:
            if len(self._buffer) == 0:
                return np.zeros((0, self.channels), dtype=np.float32)
            return self._buffer[-count:].copy()

    def get_recent_and_context(self, recent_seconds=0.7, context_seconds=8.0):
        return (
            self.get_last_seconds(recent_seconds),
            self.get_last_seconds(context_seconds),
        )

    @staticmethod
    def rms(samples):
        if samples is None or len(samples) == 0:
            return 0.0
        arr = np.asarray(samples, dtype=np.float32)
        return float(np.sqrt(np.mean(np.square(arr))))
