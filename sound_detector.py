"""Sound detection daemon for Barkomatic."""
import threading
import time
from datetime import datetime
from config import Config
from audio_processor import AudioProcessor
from sound_classifier import SoundClassifier
from file_logger import FileLogger


class SoundDetector:
    """Main sound detection engine. Runs in a thread, controllable via web UI."""

    def __init__(self):
        """Initialize detector components."""
        self.audio_processor = AudioProcessor()
        self.classifier = SoundClassifier()
        self.logger = FileLogger()

        self.running = False
        self.detection_count = 0
        self.start_time = None
        self.last_detection = None
        self._thread = None
        self._stop_event = threading.Event()

    def start(self):
        """Start detection in a background thread."""
        if self.running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop detection."""
        self._stop_event.set()
        self.running = False

    def get_status(self):
        """Return current status for the web API."""
        uptime = None
        if self.start_time:
            uptime = str(datetime.now() - self.start_time).split(".")[0]

        return {
            "running": self.running,
            "detection_count": self.detection_count,
            "total_logged": self.logger.get_count(),
            "uptime": uptime,
            "last_detection": self.last_detection,
            "sound_type": Config.SOUND_TYPE_NAME,
            "threshold": Config.BARK_DETECTION_THRESHOLD,
        }

    def reload_config(self):
        """Reload config values (called after web UI saves settings)."""
        Config.load()
        self.classifier.reload_config()
        print("[INFO] Configuration reloaded")

    def _run_loop(self):
        """Main detection loop."""
        self.running = True
        self.start_time = datetime.now()

        print(f"[INFO] Starting detection for: {Config.SOUND_TYPE_NAME}")
        print(f"[INFO] Listening on device: {Config.RPI_MICROPHONE_DEVICE}")
        print(f"[INFO] Threshold: {Config.BARK_DETECTION_THRESHOLD}")

        try:
            while not self._stop_event.is_set():
                audio = self.audio_processor.capture_audio_chunk()
                if audio is None:
                    continue

                features = self.audio_processor.extract_features(audio)
                if features is None:
                    continue

                is_match, confidence, frequency = self.classifier.classify(
                    features, audio
                )

                print(f"[DEBUG] conf={confidence:.4f} dB={features['decibels']:.1f}")

                if is_match:
                    self.detection_count += 1
                    explanation = self.classifier.get_explanation(
                        features, is_match, confidence
                    )
                    print(f"[#{self.detection_count}] {explanation}")

                    self.logger.log_event(
                        decibels=features["decibels"],
                        frequency_hz=frequency,
                        confidence=confidence,
                        features=features,
                    )

                    self.last_detection = {
                        "timestamp": datetime.now(
                            Config.get_timezone()
                        ).strftime("%Y-%m-%d %H:%M:%S %Z"),
                        "decibels": round(features["decibels"], 1),
                        "frequency_hz": round(frequency, 0),
                        "confidence": round(confidence, 3),
                    }

        except Exception as e:
            print(f"[ERROR] Detector crashed: {e}")
        finally:
            self.running = False
            elapsed = datetime.now() - self.start_time if self.start_time else "unknown"
            print(f"[INFO] Detection stopped. Uptime: {elapsed}")
            print(f"[INFO] Total detections: {self.detection_count}")
