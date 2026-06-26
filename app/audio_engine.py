import sounddevice as sd


class AudioEngine:
    def __init__(self, audio_buffer, device_id=None, device_name=None, sample_rate=44100, channels=2):
        self.audio_buffer = audio_buffer
        self.device_id = device_id
        self.device_name = device_name
        self.sample_rate = int(sample_rate)
        self.channels = int(max(1, channels))
        self.stream = None

        if self.device_id is None:
            self.device_id = self.find_device()

    @staticmethod
    def list_input_devices():
        devices = sd.query_devices()
        result = []
        for i, dev in enumerate(devices):
            max_input = int(dev.get("max_input_channels", 0))
            if max_input > 0:
                result.append({
                    "id": i,
                    "name": dev.get("name", f"Device {i}"),
                    "max_input_channels": max_input,
                    "default_samplerate": int(dev.get("default_samplerate", 44100) or 44100),
                })
        return result

    def find_device(self):
        devices = sd.query_devices()
        if self.device_name:
            for i, dev in enumerate(devices):
                if self.device_name in dev["name"] and int(dev["max_input_channels"]) >= self.channels:
                    print(f"Audio device found: {i} | {dev['name']}")
                    return i
            raise RuntimeError(f"Audio device not found: {self.device_name}")

        default_input = sd.default.device[0]
        if default_input is not None and default_input >= 0:
            return int(default_input)

        inputs = self.list_input_devices()
        if inputs:
            return int(inputs[0]["id"])

        raise RuntimeError("No audio input devices found.")

    def start(self):
        print("Starting audio stream...")
        print(f"Audio device ID: {self.device_id}, sample rate: {self.sample_rate}, channels: {self.channels}")
        self.stream = sd.InputStream(
            device=self.device_id,
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="float32",
            callback=self._callback,
        )
        self.stream.start()
        print("Audio stream started.")

    def stop(self):
        if self.stream:
            print("Stopping audio stream...")
            self.stream.stop()
            self.stream.close()
            self.stream = None
            print("Audio stream stopped.")

    def _callback(self, indata, frames, time_info, status):
        if status:
            print(status)
        self.audio_buffer.add(indata.copy())
