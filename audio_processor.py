"""Audio capture and feature extraction."""
import os
import numpy as np
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

        # Names that indicate the onboard audio (no mic input)
        ONBOARD_NAMES = {'bcm2835', 'vc4', 'hdmi'}

        # Use arecord -l to find real hardware devices
        try:
            result = subprocess.run(['arecord', '-l'], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                usb_devices = []
                hat_devices = []
                all_devices = []

                for line in result.stdout.split('\n'):
                    m = re.match(r'card (\d+):.*\[(.+?)\].*device (\d+):', line)
                    if m:
                        card, name, dev = m.group(1), m.group(2).strip(), m.group(3)
                        hw_id = f"hw:{card},{dev}"
                        name_lower = name.lower()
                        all_devices.append((hw_id, name))

                        if 'usb' in name_lower:
                            usb_devices.append((hw_id, name))
                        elif not any(ob in name_lower for ob in ONBOARD_NAMES):
                            # Not USB and not onboard = likely a HAT/I2S mic
                            hat_devices.append((hw_id, name))

                # Priority: USB mic > HAT/I2S mic > any non-onboard device
                for category, label in [
                    (usb_devices, "USB mic"),
                    (hat_devices, "HAT/I2S mic"),
                ]:
                    if category:
                        hw_id, name = category[0]
                        print(f"[AUDIO] Auto-detected {label}: {name} ({hw_id})")
                        return hw_id

                # Fall back to any capture device (skip onboard if possible)
                non_onboard = [(h, n) for h, n in all_devices
                               if not any(ob in n.lower() for ob in ONBOARD_NAMES)]
                fallback = non_onboard or all_devices
                if fallback:
                    hw_id, name = fallback[0]
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
            tuple: (numpy.ndarray, str) - Audio samples and temp WAV path, or (None, None) on error.
                   Caller must delete the WAV file when done (or keep it for playback).
        """
        try:
            import subprocess
            import wave
            import tempfile

            duration = Config.BARK_DETECTION_CHUNK_SIZE
            raw_device = self.device if self.device and self.device != "auto" else "hw:2,0"
            # Use plughw to let ALSA resample to the requested rate
            device = raw_device.replace("hw:", "plughw:", 1) if raw_device.startswith("hw:") else raw_device

            # Write to temp file to avoid pipe buffer issues
            tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
            tmp_path = tmp.name
            tmp.close()

            # Try mono first, fall back to stereo (some codecs like WM8960 require stereo)
            recorded = False
            for channels in [1, 2]:
                cmd = [
                    'arecord',
                    '-D', device,
                    '-f', 'S16_LE',
                    '-r', str(self.sample_rate),
                    '-c', str(channels),
                    '-d', str(int(duration)),
                    '-t', 'wav',
                    '-q',
                    tmp_path
                ]
                result = subprocess.run(cmd, capture_output=True, timeout=int(duration) + 5)
                if result.returncode == 0:
                    recorded = True
                    break

            if not recorded:
                print(f"[ERROR] arecord failed: {result.stderr.decode()}")
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                return None, None

            with wave.open(tmp_path, 'rb') as wf:
                frames = wf.readframes(wf.getnframes())
                audio = np.frombuffer(frames, dtype=np.int16)
                # Convert stereo to mono if needed
                if wf.getnchannels() == 2:
                    audio = audio.reshape(-1, 2).mean(axis=1).astype(np.int16)

            return audio.flatten(), tmp_path
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
            return None, None

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
        Extract basic audio features for classification.
        YAMNet does the heavy lifting so we only need lightweight features.

        Returns:
            dict: Feature dictionary, or None on error
        """
        if audio is None or len(audio) == 0:
            return None

        try:
            normalized = audio.astype(np.float32) / 32768.0
            decibels = self.calculate_decibels(audio)

            # Lightweight features only - no librosa heavy processing
            zcr_mean = float(np.mean(np.abs(np.diff(np.sign(normalized)))) / 2)

            # Simple spectral centroid via FFT (fast)
            fft = np.abs(np.fft.rfft(normalized))
            freqs = np.fft.rfftfreq(len(normalized), 1.0 / self.sample_rate)
            spec_centroid_mean = float(np.sum(freqs * fft) / (np.sum(fft) + 1e-10))
            spec_rolloff_mean = spec_centroid_mean * 1.5

            mfcc_mean = np.zeros(13)

            rms = float(np.sqrt(np.mean(normalized ** 2)))
            return {
                "decibels": float(decibels),
                "rms_energy": round(rms, 6),
                "zcr_mean": float(zcr_mean),
                "spec_centroid_mean": float(spec_centroid_mean),
                "spec_rolloff_mean": float(spec_rolloff_mean),
                "mfcc_mean": mfcc_mean.tolist(),
                "duration": float(len(audio) / self.sample_rate),
                "sample_rate": self.sample_rate,
                "samples": len(audio),
            }
        except Exception as e:
            print(f"[ERROR] Feature extraction failed: {e}")
            return None
