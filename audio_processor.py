"""Audio capture and feature extraction."""
import numpy as np
import librosa
import sounddevice as sd
from config import Config


class AudioProcessor:
    """Handles audio capture and feature extraction."""

    def __init__(self):
        """Initialize audio processor with auto-detection fallback."""
        self.sample_rate = Config.RPI_MICROPHONE_RATE
        self.channels = Config.RPI_MICROPHONE_CHANNELS
        self.device = self._resolve_device(Config.RPI_MICROPHONE_DEVICE)
        self.chunk_size = int(Config.BARK_DETECTION_CHUNK_SIZE * self.sample_rate)

    def _resolve_device(self, device_str):
        """
        Resolve the audio device.
        If the configured device doesn't work, try to auto-detect a USB mic.
        """
        # Try the configured device first
        if device_str and device_str != "auto":
            if self._test_device(device_str):
                print(f"[AUDIO] Using configured device: {device_str}")
                return device_str
            else:
                print(f"[AUDIO] Configured device '{device_str}' not available, auto-detecting...")

        # Auto-detect: find a USB microphone
        return self._auto_detect()

    def _test_device(self, device_str):
        """Test if an audio device is available for recording."""
        try:
            sd.check_input_settings(device=device_str, samplerate=self.sample_rate, channels=self.channels)
            return True
        except Exception:
            return False

    def _auto_detect(self):
        """Auto-detect the best input device using arecord."""
        import subprocess
        import re

        # Use arecord -l to find real hardware devices
        try:
            result = subprocess.run(['arecord', '-l'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                usb_devices = []
                all_devices = []

                for line in result.stdout.split('\n'):
                    m = re.match(r'card (\d+):.*\[(.+?)\].*device (\d+):', line)
                    if m:
                        card, name, dev = m.group(1), m.group(2).strip(), m.group(3)
                        hw_id = f"hw:{card},{dev}"
                        all_devices.append((hw_id, name))
                        if 'usb' in name.lower():
                            usb_devices.append((hw_id, name))

                # Prefer USB devices
                if usb_devices:
                    hw_id, name = usb_devices[0]
                    print(f"[AUDIO] Auto-detected USB mic: {name} ({hw_id})")
                    return hw_id

                # Fall back to any capture device
                if all_devices:
                    hw_id, name = all_devices[0]
                    print(f"[AUDIO] Using capture device: {name} ({hw_id})")
                    return hw_id

        except Exception as e:
            print(f"[AUDIO] arecord detection failed: {e}")

        # Fallback: try sounddevice
        try:
            devices = sd.query_devices()
            for i, dev in enumerate(devices):
                if dev["max_input_channels"] > 0:
                    name = dev["name"].lower()
                    if "usb" in name:
                        print(f"[AUDIO] Using sounddevice USB: {dev['name']} (index {i})")
                        return i
        except Exception:
            pass

        print("[AUDIO] No device found, using hw:2,0 as fallback")
        return "hw:2,0"

    def capture_audio_chunk(self):
        """
        Capture a chunk of audio from the microphone.

        Returns:
            numpy.ndarray: Audio samples as 1D array, or None on error
        """
        try:
            import subprocess
            import io
            import wave

            duration = Config.BARK_DETECTION_CHUNK_SIZE
            device = self.device if self.device and self.device != "auto" else "hw:2,0"

            # Use arecord directly - more reliable on RPI than sounddevice
            cmd = [
                'arecord',
                '-D', device,
                '-f', 'S16_LE',
                '-r', str(self.sample_rate),
                '-c', '1',
                '-d', str(int(duration)),
                '-t', 'wav',
                '-q',
                '-'
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=int(duration) + 5)

            if result.returncode != 0:
                print(f"[ERROR] arecord failed: {result.stderr.decode()}")
                return None

            # Parse WAV from stdout
            wav_data = io.BytesIO(result.stdout)
            with wave.open(wav_data, 'rb') as wf:
                frames = wf.readframes(wf.getnframes())
                audio = np.frombuffer(frames, dtype=np.int16)

            return audio.flatten()
        except Exception as e:
            print(f"[ERROR] Audio capture failed: {e}")
            # Try to recover by re-detecting the device
            try:
                new_device = self._auto_detect()
                if new_device != self.device:
                    print(f"[AUDIO] Switching to: {new_device}")
                    self.device = new_device
            except Exception:
                pass
            return None

    def calculate_decibels(self, audio):
        """Calculate RMS-based decibel level from audio samples."""
        if audio is None or len(audio) == 0:
            return -np.inf

        normalized = audio.astype(np.float32) / 32768.0
        rms = np.sqrt(np.mean(normalized ** 2))

        if rms > 0:
            db = 20 * np.log10(rms)
        else:
            db = -np.inf

        return db

    def extract_features(self, audio):
        """
        Extract audio features for classification.

        Returns:
            dict: Feature dictionary, or None on error
        """
        if audio is None or len(audio) == 0:
            return None

        try:
            normalized = audio.astype(np.float32) / 32768.0
            decibels = self.calculate_decibels(audio)

            zcr = librosa.feature.zero_crossing_rate(normalized)[0]
            zcr_mean = np.mean(zcr)

            spec_centroid = librosa.feature.spectral_centroid(
                y=normalized, sr=self.sample_rate
            )[0]
            spec_centroid_mean = np.mean(spec_centroid)

            mfcc = librosa.feature.mfcc(
                y=normalized, sr=self.sample_rate, n_mfcc=13
            )
            mfcc_mean = np.mean(mfcc, axis=1)

            spec_rolloff = librosa.feature.spectral_rolloff(
                y=normalized, sr=self.sample_rate
            )[0]
            spec_rolloff_mean = np.mean(spec_rolloff)

            return {
                "decibels": float(decibels),
                "zcr_mean": float(zcr_mean),
                "spec_centroid_mean": float(spec_centroid_mean),
                "spec_rolloff_mean": float(spec_rolloff_mean),
                "mfcc_mean": mfcc_mean.tolist(),
                "duration": float(len(audio) / self.sample_rate),
            }
        except Exception as e:
            print(f"[ERROR] Feature extraction failed: {e}")
            return None
