"""Sound detection daemon for Barkomatic."""
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timedelta
from config import Config
from audio_processor import AudioProcessor
from sound_classifier import SoundClassifier
from file_logger import FileLogger

# Directory to store detection audio clips
AUDIO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recordings")
SNAPSHOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshots")
LIVE_SNAPSHOT_FILE = "live.jpg"


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
        self.last_audio_db = None
        self.audio_present = False
        self.last_snapshot_file = ""
        self.camera_available = None
        self._thread = None
        self._stop_event = threading.Event()
        self._snapshot_lock = threading.Lock()

        # Ensure recordings directory exists
        os.makedirs(AUDIO_DIR, exist_ok=True)
        os.makedirs(SNAPSHOT_DIR, exist_ok=True)

    def _get_disk_stats(self):
        """Return current disk usage stats for the recordings volume."""
        disk = shutil.disk_usage(AUDIO_DIR)
        free_gb = round(disk.free / (1024 ** 3), 1)
        total_gb = round(disk.total / (1024 ** 3), 1)
        free_pct = round((disk.free / disk.total) * 100, 1) if disk.total else 0.0
        used_pct = round(100.0 - free_pct, 1)
        recording_blocked = used_pct >= 95.0
        return {
            "disk_free_gb": free_gb,
            "disk_total_gb": total_gb,
            "disk_free_pct": free_pct,
            "disk_used_pct": used_pct,
            "recording_blocked_low_disk": recording_blocked,
        }

    def _capture_snapshot(self, output_path, timeout_ms=1000):
        """Capture a still image from the Pi camera."""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        temp_path = output_path + ".tmp"

        cmd = [
            "rpicam-still",
            "-o",
            temp_path,
            "--nopreview",
            "--timeout",
            str(int(timeout_ms)),
            "--width",
            "1280",
            "--height",
            "720",
            "--quality",
            "90",
        ]

        try:
            with self._snapshot_lock:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=max(6, int(timeout_ms / 1000) + 5),
                )

                if result.returncode != 0:
                    self.camera_available = False
                    if os.path.exists(temp_path):
                        os.unlink(temp_path)
                    stderr = (result.stderr or "").strip()
                    print(f"[CAMERA] Snapshot failed: {stderr or 'unknown error'}")
                    return False

                os.replace(temp_path, output_path)

            self.camera_available = True
            return True
        except FileNotFoundError:
            self.camera_available = False
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            print("[CAMERA] rpicam-still not found")
            return False
        except Exception as exc:
            self.camera_available = False
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            print(f"[CAMERA] Snapshot failed: {exc}")
            return False

    def capture_live_snapshot(self):
        """Capture and return the latest live snapshot path."""
        live_path = os.path.join(SNAPSHOT_DIR, LIVE_SNAPSHOT_FILE)
        if self._capture_snapshot(live_path, timeout_ms=700):
            return live_path
        return live_path if os.path.exists(live_path) else None

    def capture_recording_snapshot(self, stem):
        """Capture a snapshot tied to a saved audio recording."""
        snapshot_filename = f"{stem}.jpg"
        snapshot_path = os.path.join(SNAPSHOT_DIR, snapshot_filename)
        if self._capture_snapshot(snapshot_path, timeout_ms=700):
            self.last_snapshot_file = snapshot_filename
            return snapshot_filename
        return ""

    def get_snapshot_path(self, filename):
        """Return the absolute path for a saved snapshot filename."""
        return os.path.join(SNAPSHOT_DIR, filename)

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
        disk_stats = self._get_disk_stats()

        return {
            "running": self.running,
            "detection_count": self.detection_count,
            "total_logged": self.logger.get_count(),
            "uptime": uptime,
            "last_detection": self.last_detection,
            "last_audio_db": self.last_audio_db,
            "audio_present": self.audio_present,
            "sound_type": "All sounds",
            "record_sound_indices": Config.RECORD_SOUND_INDICES,
            "threshold": Config.BARK_DETECTION_THRESHOLD,
            "last_snapshot_file": self.last_snapshot_file,
            "camera_available": self.camera_available,
            **disk_stats,
        }

    def cleanup_old_recordings(self, days=30):
        """Delete recordings and logged events older than the given number of days."""
        cutoff = datetime.now() - timedelta(days=days)
        deleted_files = 0
        freed_bytes = 0

        for media_dir in (AUDIO_DIR, SNAPSHOT_DIR):
            for entry in os.scandir(media_dir):
                if not entry.is_file():
                    continue
                try:
                    modified = datetime.fromtimestamp(entry.stat().st_mtime)
                    if modified >= cutoff:
                        continue
                    size = entry.stat().st_size
                    os.unlink(entry.path)
                    deleted_files += 1
                    freed_bytes += size
                except FileNotFoundError:
                    continue

        log_result = self.logger.cleanup_old_events(days=days)

        return {
            "deleted_files": deleted_files,
            "freed_mb": round(freed_bytes / (1024 ** 2), 1),
            "deleted_logs": log_result["deleted_logs"],
        }

    def reload_config(self):
        """Reload config values (called after web UI saves settings)."""
        Config.load()
        self.classifier.reload_config()
        self._migrate_record_names()
        print("[INFO] Configuration reloaded")

    def _migrate_record_names(self):
        """Populate RECORD_SOUND_NAMES from current class map if empty but indices are set."""
        if Config.RECORD_SOUND_NAMES or not Config.RECORD_SOUND_INDICES:
            return
        if not self.classifier.class_labels:
            return
        Config.RECORD_SOUND_NAMES = [
            self.classifier.class_labels[i]
            for i in Config.RECORD_SOUND_INDICES
            if i in self.classifier.class_labels
        ]
        if Config.RECORD_SOUND_NAMES:
            Config.save()
            print(f"[INFO] Migrated record names: {Config.RECORD_SOUND_NAMES}")

    def _run_loop(self):
        """Main detection loop."""
        self.running = True
        self.start_time = datetime.now()

        self._migrate_record_names()
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

                self.last_audio_db = round(features.get("decibels", -100.0), 1)
                self.audio_present = self.last_audio_db > -65.0

                matches, frequency, yamnet_scores = self.classifier.classify_all(
                    features, audio
                )

                if matches:
                    self.detection_count += len(matches)
                    explanation = self.classifier.get_explanation(features, matches)
                    print(f"[#{self.detection_count}] {explanation}")
                    top_match = matches[0]

                    disk_stats = self._get_disk_stats()
                    record_names = set(Config.RECORD_SOUND_NAMES or [])
                    record_indices = set(Config.RECORD_SOUND_INDICES or [])
                    matched = (
                        (record_names and top_match["name"] in record_names)
                        or (not record_names and top_match["index"] in record_indices)
                    )
                    should_record = matched and not disk_stats["recording_blocked_low_disk"]

                    audio_filename = ""
                    snapshot_filename = ""
                    if should_record and wav_path and os.path.exists(wav_path):
                        now = datetime.now(Config.get_timezone())
                        stem = now.strftime("%Y%m%d_%H%M%S")
                        audio_filename = stem + ".wav"
                        dest = os.path.join(AUDIO_DIR, audio_filename)
                        shutil.move(wav_path, dest)
                        wav_path = None  # Don't delete below
                        print(f"[AUDIO] Saved clip: {audio_filename}")
                        # Snapshot runs in background so it doesn't stall the detection loop
                        threading.Thread(
                            target=self.capture_recording_snapshot,
                            args=(stem,),
                            daemon=True,
                        ).start()

                    for match in matches:
                        self.logger.log_event(
                            sound_type=match["name"],
                            class_index=match["index"],
                            decibels=features["decibels"],
                            frequency_hz=frequency,
                            confidence=match["confidence"],
                            features=features,
                            audio_file=audio_filename,
                            snapshot_file=snapshot_filename,
                            yamnet_scores=yamnet_scores,
                        )

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
