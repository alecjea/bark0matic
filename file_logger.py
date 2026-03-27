"""SQLite-backed logger for sound detection events."""
import csv
import json
import os
import sqlite3
import threading
from datetime import datetime

from config import Config


class FileLogger:
    """Logs detection events to a SQLite database and exports CSV on demand."""

    HEADER = [
        "timestamp",
        "sound_type",
        "decibels",
        "rms_energy",
        "frequency_hz",
        "confidence",
        "duration_seconds",
        "dog_size",
        "audio_file",
        "json_payload",
    ]

    def __init__(self):
        """Initialize the SQLite logger."""
        self.db_path = Config.LOG_DB_PATH
        self.csv_export_path = os.path.splitext(self.db_path)[0] + "_export.csv"
        self.legacy_csv_path = os.path.join(
            os.path.dirname(os.path.abspath(self.db_path)), "detections.csv"
        )
        self._lock = threading.Lock()
        self._initialize_database()
        print(f"[LOG] Logging to {self.db_path}")

    def _connect(self):
        """Open a new SQLite connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize_database(self):
        """Create database and migrate legacy CSV data if needed."""
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)

        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS detections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    sound_type TEXT NOT NULL,
                    decibels REAL NOT NULL,
                    rms_energy REAL NOT NULL,
                    frequency_hz REAL NOT NULL,
                    confidence REAL NOT NULL,
                    duration_seconds REAL NOT NULL,
                    dog_size TEXT NOT NULL DEFAULT '',
                    audio_file TEXT NOT NULL DEFAULT '',
                    json_payload TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.commit()

        self._migrate_legacy_csv_if_needed()

    def _migrate_legacy_csv_if_needed(self):
        """Import detections from the old CSV log if the database is empty."""
        if not os.path.exists(self.legacy_csv_path) or self.legacy_csv_path == self.db_path:
            return

        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM detections").fetchone()
            if row["count"] > 0:
                return

        try:
            with open(self.legacy_csv_path, "r", newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)

            if not rows:
                return

            with self._connect() as conn:
                conn.executemany(
                    """
                    INSERT INTO detections (
                        timestamp, sound_type, decibels, rms_energy, frequency_hz,
                        confidence, duration_seconds, dog_size, audio_file, json_payload
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            (row.get("timestamp") or "").strip(),
                            row.get("sound_type") or "",
                            float(row.get("decibels") or 0),
                            float(row.get("rms_energy") or 0),
                            float(row.get("frequency_hz") or 0),
                            float(row.get("confidence") or 0),
                            float(row.get("duration_seconds") or 0),
                            row.get("dog_size") or "",
                            row.get("audio_file") or "",
                            row.get("json_payload") or "",
                        )
                        for row in reversed(rows)
                    ],
                )
                conn.commit()

            print(f"[LOG] Migrated {len(rows)} legacy detections from CSV")
        except Exception as exc:
            print(f"[ERROR] Failed to migrate legacy CSV log: {exc}")

    def _row_to_dict(self, row):
        """Normalize a SQLite row for API responses and exports."""
        data = dict(row)
        for key in self.HEADER:
            value = data.get(key)
            data[key] = "" if value is None else str(value)
        return data

    def log_event(
        self,
        decibels,
        frequency_hz,
        confidence,
        features,
        audio_file="",
        yamnet_scores=None,
    ):
        """Log a detected sound event."""
        now = datetime.now(Config.get_timezone())
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S %Z")
        duration = features.get("duration", 0) if features else 0
        rms_energy = features.get("rms_energy", 0) if features else 0

        dog_size = ""
        if Config.SOUND_TYPE_NAME.lower() in ("dog bark", "dog"):
            if frequency_hz < Config.DOG_SIZE_FREQUENCY_THRESHOLD:
                dog_size = "Large dog"
            else:
                dog_size = "Small dog"

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

        if yamnet_scores:
            top10 = sorted(enumerate(yamnet_scores), key=lambda x: x[1], reverse=True)[:10]
            payload["yamnet_top10"] = [{"index": i, "score": round(s, 4)} for i, s in top10]

        payload_json = json.dumps(payload, separators=(",", ":"))

        try:
            with self._lock:
                with self._connect() as conn:
                    conn.execute(
                        """
                        INSERT INTO detections (
                            timestamp, sound_type, decibels, rms_energy, frequency_hz,
                            confidence, duration_seconds, dog_size, audio_file, json_payload
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            timestamp,
                            Config.SOUND_TYPE_NAME,
                            round(decibels, 1),
                            float(rms_energy),
                            round(frequency_hz, 0),
                            round(confidence, 3),
                            round(duration, 1),
                            dog_size,
                            audio_file,
                            payload_json,
                        ),
                    )
                    conn.commit()

            dog_info = f" | {dog_size}" if dog_size else ""
            print(
                f"[LOG] {timestamp} | {Config.SOUND_TYPE_NAME} | "
                f"{decibels:.1f}dB | rms:{rms_energy:.4f} | {frequency_hz:.0f}Hz | "
                f"conf:{confidence:.2f}{dog_info}"
            )
        except Exception as exc:
            print(f"[ERROR] Failed to log event: {exc}")

    def get_recent(self, count=100):
        """Get recent detection events, newest first."""
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT
                        timestamp, sound_type, decibels, rms_energy, frequency_hz,
                        confidence, duration_seconds, dog_size, audio_file, json_payload
                    FROM detections
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (max(0, int(count)),),
                ).fetchall()
            return [self._row_to_dict(row) for row in rows]
        except Exception as exc:
            print(f"[ERROR] Failed to read events: {exc}")
            return []

    def export_csv(self):
        """Export the current SQLite log to a CSV file and return its path."""
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT
                        timestamp, sound_type, decibels, rms_energy, frequency_hz,
                        confidence, duration_seconds, dog_size, audio_file, json_payload
                    FROM detections
                    ORDER BY id DESC
                    """
                ).fetchall()

            with open(self.csv_export_path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(self.HEADER)
                for row in rows:
                    item = self._row_to_dict(row)
                    writer.writerow([item[column] for column in self.HEADER])

            return self.csv_export_path
        except Exception as exc:
            print(f"[ERROR] Failed to export CSV: {exc}")
            raise

    def get_csv_path(self):
        """Return a freshly exported CSV path for dashboard downloads."""
        return self.export_csv()

    def clear(self):
        """Clear all logged events."""
        try:
            with self._lock:
                with self._connect() as conn:
                    conn.execute("DELETE FROM detections")
                    conn.commit()
            print("[LOG] Log cleared")
        except Exception as exc:
            print(f"[ERROR] Failed to clear log: {exc}")
            raise

    def get_count(self):
        """Return total number of logged events."""
        try:
            with self._connect() as conn:
                row = conn.execute("SELECT COUNT(*) AS count FROM detections").fetchone()
            return int(row["count"]) if row else 0
        except Exception:
            return 0
