"""CSV file logger for sound detection events."""
import csv
import json
import os
from datetime import datetime
from config import Config


class FileLogger:
    """Logs detection events to a CSV file."""

    HEADER = ["timestamp", "sound_type", "decibels", "rms_energy", "frequency_hz", "confidence", "duration_seconds", "dog_size", "audio_file", "json_payload"]

    def __init__(self):
        """Initialize the CSV logger."""
        self.csv_path = Config.LOG_FILE_PATH
        self._ensure_file()
        print(f"[LOG] Logging to {self.csv_path}")

    def _ensure_file(self):
        """Create CSV with header if it doesn't exist."""
        if not os.path.exists(self.csv_path):
            with open(self.csv_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(self.HEADER)

    def log_event(self, decibels, frequency_hz, confidence, features, audio_file="", yamnet_scores=None):
        """
        Log a detected sound event.

        Args:
            decibels: Sound level in dB
            frequency_hz: Primary frequency in Hz
            confidence: Detection confidence 0-1
            features: Raw audio features dict
            audio_file: Filename of saved audio clip (optional)
            yamnet_scores: Full YAMNet score array (optional)
        """
        now = datetime.now(Config.get_timezone())
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S %Z")
        duration = features.get("duration", 0) if features else 0
        rms_energy = features.get("rms_energy", 0) if features else 0

        # Determine dog size based on frequency (only for dog bark detection)
        dog_size = ""
        if Config.SOUND_TYPE_NAME.lower() in ("dog bark", "dog"):
            dog_size = "Large dog" if frequency_hz < 2000 else "Small dog"

        # Build full JSON payload
        payload = {
            "timestamp": timestamp,
            "sound_type": Config.SOUND_TYPE_NAME,
            "confidence": round(confidence, 4),
            "decibels": round(decibels, 2),
            "rms_energy": rms_energy,
            "frequency_hz": round(frequency_hz, 1),
            "duration_seconds": round(duration, 2),
            "dog_size": dog_size,
            "audio_file": audio_file,
            "features": {k: v for k, v in (features or {}).items() if k != "mfcc_mean"},
            "threshold_used": Config.BARK_DETECTION_THRESHOLD,
            "energy_threshold_used": Config.BARK_DETECTION_ENERGY_THRESHOLD,
            "yamnet_top10": [],
        }

        # Add top 10 YAMNet scores with indices
        if yamnet_scores:
            top10 = sorted(enumerate(yamnet_scores), key=lambda x: x[1], reverse=True)[:10]
            payload["yamnet_top10"] = [{"index": i, "score": round(s, 4)} for i, s in top10]

        payload_json = json.dumps(payload, separators=(",", ":"))

        try:
            # Read existing content
            lines = []
            if os.path.exists(self.csv_path):
                with open(self.csv_path, "r", newline="") as f:
                    lines = f.readlines()

            # Use csv writer to handle JSON with commas/quotes safely
            import io
            row_buf = io.StringIO()
            writer = csv.writer(row_buf)
            writer.writerow([
                timestamp, Config.SOUND_TYPE_NAME,
                f"{decibels:.1f}", f"{rms_energy:.6f}", f"{frequency_hz:.0f}",
                f"{confidence:.3f}", f"{duration:.1f}", dog_size, audio_file,
                payload_json
            ])
            new_row = row_buf.getvalue()

            # Write header + new row at top + rest
            with open(self.csv_path, "w", newline="") as f:
                if lines:
                    f.write(lines[0])  # header
                    f.write(new_row)
                    f.writelines(lines[1:])  # existing rows
                else:
                    f.write(",".join(self.HEADER) + "\n")
                    f.write(new_row)

            dog_info = f" | {dog_size}" if dog_size else ""
            print(
                f"[LOG] {timestamp} | {Config.SOUND_TYPE_NAME} | "
                f"{decibels:.1f}dB | rms:{rms_energy:.4f} | {frequency_hz:.0f}Hz | conf:{confidence:.2f}{dog_info}"
            )
        except Exception as e:
            print(f"[ERROR] Failed to log event: {e}")

    def get_recent(self, count=100):
        """
        Get recent detection events.

        Args:
            count: Maximum number of events to return

        Returns:
            list of dicts, newest first
        """
        try:
            if not os.path.exists(self.csv_path):
                return []

            with open(self.csv_path, "r") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            # Replace None values with empty strings (old rows missing new columns)
            for row in rows:
                for key in row:
                    if row[key] is None:
                        row[key] = ""

            # Already newest first, just limit
            return rows[:count]
        except Exception as e:
            print(f"[ERROR] Failed to read events: {e}")
            return []

    def get_csv_path(self):
        """Return the path to the CSV file for download."""
        return self.csv_path

    def clear(self):
        """Clear all logged events (reset to header only)."""
        try:
            with open(self.csv_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(self.HEADER)
            print("[LOG] Log cleared")
        except Exception as e:
            print(f"[ERROR] Failed to clear log: {e}")
            raise

    def get_count(self):
        """Return total number of logged events."""
        try:
            if not os.path.exists(self.csv_path):
                return 0
            with open(self.csv_path, "r") as f:
                return max(0, sum(1 for _ in f) - 1)  # minus header
        except Exception:
            return 0
