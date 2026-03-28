"""Sound detection daemon for Barkomatic."""
import os
import shutil
import threading
import time
from datetime import datetime
from config import Config
from audio_processor import AudioProcessor
from sound_classifier import SoundClassifier
from file_logger import FileLogger

# Directory to store detection audio clips
AUDIO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recordings")


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

        # Ensure recordings directory exists
        os.makedirs(AUDIO_DIR, exist_ok=True)

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
            "sound_type": "All sounds",
            "record_sound_indices": Config.RECORD_SOUND_INDICES,
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

        print("[INFO] Starting detection for: all sounds")
        print(f"[INFO] Listening on device: {Config.RPI_MICROPHONE_DEVICE}")
        print(f"[INFO] Threshold: {Config.BARK_DETECTION_THRESHOLD}")

        try:
            while not self._stop_event.is_set():
                audio, wav_path = self.audio_processor.capture_audio_chunk()
                if audio is None:
                    continue

                features = self.audio_processor.extract_features(audio)
                if features is None:
                    if wav_path and os.path.exists(wav_path):
                        os.unlink(wav_path)
                    continue

                matches, frequency, yamnet_scores = self.classifier.classify_all(
                    features, audio
                )

                if matches:
                    self.detection_count += len(matches)
                    explanation = self.classifier.get_explanation(features, matches)
                    print(f"[#{self.detection_count}] {explanation}")

                    should_record = any(
                        match["index"] in set(Config.RECORD_SOUND_INDICES or [])
                        for match in matches
                    )

                    audio_filename = ""
                    if should_record and wav_path and os.path.exists(wav_path):
                        now = datetime.now(Config.get_timezone())
                        audio_filename = now.strftime("%Y%m%d_%H%M%S") + ".wav"
                        dest = os.path.join(AUDIO_DIR, audio_filename)
                        shutil.move(wav_path, dest)
                        wav_path = None  # Don't delete below
                        print(f"[AUDIO] Saved clip: {audio_filename}")

                    for match in matches:
                        self.logger.log_event(
                            sound_type=match["name"],
                            class_index=match["index"],
                            decibels=features["decibels"],
                            frequency_hz=frequency,
                            confidence=match["confidence"],
                            features=features,
                            audio_file=audio_filename,
                            yamnet_scores=yamnet_scores,
                        )

                    top_match = matches[0]

                    self.last_detection = {
                        "timestamp": datetime.now(
                            Config.get_timezone()
                        ).strftime("%Y-%m-%d %H:%M:%S %Z"),
                        "sound_type": top_match["name"],
                        "decibels": round(features["decibels"], 1),
                        "frequency_hz": round(frequency, 0),
                        "confidence": round(top_match["confidence"], 3),
                    }

                # Clean up temp file if not saved
                if wav_path and os.path.exists(wav_path):
                    os.unlink(wav_path)

        except Exception as e:
            print(f"[ERROR] Detector crashed: {e}")
        finally:
            self.running = False
            elapsed = datetime.now() - self.start_time if self.start_time else "unknown"
            print(f"[INFO] Detection stopped. Uptime: {elapsed}")
            print(f"[INFO] Total detections: {self.detection_count}")
