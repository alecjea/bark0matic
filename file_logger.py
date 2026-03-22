"""CSV file logger for sound detection events."""
import csv
import os
from datetime import datetime
from config import Config


class FileLogger:
    """Logs detection events to a CSV file."""

    HEADER = ["timestamp", "sound_type", "decibels", "frequency_hz", "confidence", "duration_seconds"]

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

    def log_event(self, decibels, frequency_hz, confidence, features):
        """
        Log a detected sound event.

        Args:
            decibels: Sound level in dB
            frequency_hz: Primary frequency in Hz
            confidence: Detection confidence 0-1
            features: Raw audio features dict
        """
        now = datetime.now(Config.get_timezone())
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S %Z")
        duration = features.get("duration", 0) if features else 0

        try:
            with open(self.csv_path, "a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    timestamp,
                    Config.SOUND_TYPE_NAME,
                    f"{decibels:.1f}",
                    f"{frequency_hz:.0f}",
                    f"{confidence:.3f}",
                    f"{duration:.1f}",
                ])
            print(
                f"[LOG] {timestamp} | {Config.SOUND_TYPE_NAME} | "
                f"{decibels:.1f}dB | {frequency_hz:.0f}Hz | conf:{confidence:.2f}"
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

            # Return newest first, limited to count
            return rows[-count:][::-1]
        except Exception as e:
            print(f"[ERROR] Failed to read events: {e}")
            return []

    def get_csv_path(self):
        """Return the path to the CSV file for download."""
        return self.csv_path

    def get_count(self):
        """Return total number of logged events."""
        try:
            if not os.path.exists(self.csv_path):
                return 0
            with open(self.csv_path, "r") as f:
                return max(0, sum(1 for _ in f) - 1)  # minus header
        except Exception:
            return 0
