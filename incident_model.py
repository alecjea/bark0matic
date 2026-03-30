"""Incident model — groups raw YAMNet detections into complaint-ready incidents."""
import sqlite3
import uuid
from datetime import datetime

from config import Config
from quiet_hours import is_quiet_hours

# Merge window: detections of the same event_type within this many seconds are one incident.
GROUPING_WINDOW_SECONDS = 30

VALID_EVENT_TYPES = frozenset({
    "dog_barking",
    "amplified_music",
    "shouting",
    "impact_banging",
    "sustained_loud_noise",
    "unknown_nuisance_noise",
})

VALID_REVIEW_STATUSES = frozenset({"pending", "reviewed", "dismissed"})


def map_sound_type_to_event_type(sound_type: str) -> str:
    """Map a YAMNet sound_type label to a Sentinel incident event_type."""
    s = (sound_type or "").lower()
    if "dog" in s or "bark" in s:
        return "dog_barking"
    if "music" in s or "sing" in s or "song" in s or "instrument" in s:
        return "amplified_music"
    if "shout" in s or "scream" in s or "cry" in s or "yell" in s or "sob" in s:
        return "shouting"
    if "knock" in s or "bang" in s or "impact" in s or "glass" in s or "break" in s or "crack" in s:
        return "impact_banging"
    if "engine" in s or "motor" in s or "drill" in s or "alarm" in s or "siren" in s or "rev" in s:
        return "sustained_loud_noise"
    return "unknown_nuisance_noise"


def compute_severity_score(duration_seconds: float, peak_db: float, confidence: float) -> float:
    """Compute a 0-1 severity score from duration, peak_db, and confidence.

    Weights:
      40% duration  — normalised over 0-300 s
      30% peak_db   — normalised over 40-100 dBFS
      30% confidence — already 0-1
    """
    dur_score = min(max(duration_seconds, 0.0) / 300.0, 1.0)
    db_score = min(max(peak_db - 40.0, 0.0) / 60.0, 1.0)
    conf_score = min(max(confidence, 0.0), 1.0)
    return round(0.4 * dur_score + 0.3 * db_score + 0.3 * conf_score, 4)


_SCHEMA_INCIDENTS = """
    CREATE TABLE IF NOT EXISTS incidents (
        incident_id      TEXT PRIMARY KEY,
        case_id          TEXT,
        device_id        TEXT NOT NULL DEFAULT '',
        event_type       TEXT NOT NULL,
        started_at       TEXT NOT NULL,
        ended_at         TEXT NOT NULL,
        duration_seconds REAL NOT NULL DEFAULT 0,
        peak_db          REAL NOT NULL DEFAULT 0,
        average_db       REAL NOT NULL DEFAULT 0,
        confidence       REAL NOT NULL DEFAULT 0,
        severity_score   REAL NOT NULL DEFAULT 0,
        quiet_hours_violation INTEGER NOT NULL DEFAULT 0,
        tenant_marked    INTEGER NOT NULL DEFAULT 0,
        review_status    TEXT NOT NULL DEFAULT 'pending',
        tamper_flags     TEXT,
        retention_class  TEXT NOT NULL DEFAULT 'standard',
        media_ref        TEXT,
        detection_count  INTEGER NOT NULL DEFAULT 1
    )
"""


class IncidentManager:
    """Manages the incidents table and detection-grouping logic."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_schema()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self):
        with self._connect() as conn:
            conn.execute(_SCHEMA_INCIDENTS)
            # Add incident_id tracking column to existing detections table
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(detections)").fetchall()}
            if "incident_id" not in cols:
                conn.execute("ALTER TABLE detections ADD COLUMN incident_id TEXT")
            conn.commit()

    @staticmethod
    def _parse_ts(ts_str: str):
        for fmt in ("%Y-%m-%d %H:%M:%S %Z", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime((ts_str or "").strip(), fmt)
            except ValueError:
                continue
        return None

    # ------------------------------------------------------------------
    # Grouping
    # ------------------------------------------------------------------

    def process_new_detections(self):
        """Group any unprocessed detections into incidents (idempotent)."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, timestamp, sound_type, decibels, confidence,
                       duration_seconds, audio_file
                FROM detections
                WHERE incident_id IS NULL
                ORDER BY id ASC
                """
            ).fetchall()

        if not rows:
            return

        # Parse and annotate each detection
        parsed = []
        for row in rows:
            ts = self._parse_ts(row["timestamp"])
            if ts is None:
                continue
            parsed.append({
                "id": row["id"],
                "ts": ts,
                "event_type": map_sound_type_to_event_type(row["sound_type"]),
                "decibels": float(row["decibels"] or 0),
                "confidence": float(row["confidence"] or 0),
                "duration_seconds": float(row["duration_seconds"] or 0),
                "audio_file": row["audio_file"] or "",
            })

        if not parsed:
            return

        parsed.sort(key=lambda x: x["ts"])

        # Greedy merge: same event_type and ≤30 s gap
        groups: list[list[dict]] = [[parsed[0]]]
        for item in parsed[1:]:
            last = groups[-1][-1]
            gap = (item["ts"] - last["ts"]).total_seconds()
            if item["event_type"] == last["event_type"] and gap <= GROUPING_WINDOW_SECONDS:
                groups[-1].append(item)
            else:
                groups.append([item])

        # Persist incidents and back-fill detection.incident_id
        with self._connect() as conn:
            for group in groups:
                inc_id = str(uuid.uuid4())
                event_type = group[0]["event_type"]
                started_at = group[0]["ts"].strftime("%Y-%m-%dT%H:%M:%S")
                ended_at = group[-1]["ts"].strftime("%Y-%m-%dT%H:%M:%S")

                # Duration: at least the span between first and last, plus the last clip length
                span = (group[-1]["ts"] - group[0]["ts"]).total_seconds()
                detection_dur_sum = sum(d["duration_seconds"] for d in group)
                total_duration = max(span + group[-1]["duration_seconds"], detection_dur_sum)

                peak_db = max(d["decibels"] for d in group)
                average_db = sum(d["decibels"] for d in group) / len(group)
                avg_confidence = sum(d["confidence"] for d in group) / len(group)
                severity = compute_severity_score(total_duration, peak_db, avg_confidence)
                media_ref = next((d["audio_file"] for d in group if d["audio_file"]), None)

                conn.execute(
                    """
                    INSERT INTO incidents (
                        incident_id, device_id, event_type,
                        started_at, ended_at, duration_seconds,
                        peak_db, average_db, confidence, severity_score,
                        quiet_hours_violation, review_status,
                        retention_class, media_ref, detection_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        inc_id,
                        Config.RPI_MICROPHONE_DEVICE,
                        event_type,
                        started_at,
                        ended_at,
                        round(total_duration, 2),
                        round(peak_db, 1),
                        round(average_db, 1),
                        round(avg_confidence, 3),
                        severity,
                        1 if is_quiet_hours(started_at, Config) else 0,
                        "pending",
                        "standard",
                        media_ref,
                        len(group),
                    ),
                )

                det_ids = [d["id"] for d in group]
                placeholders = ",".join("?" * len(det_ids))
                conn.execute(
                    f"UPDATE detections SET incident_id = ? WHERE id IN ({placeholders})",
                    [inc_id] + det_ids,
                )

            conn.commit()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_recent_incidents(
        self,
        count: int = 50,
        event_type: str = None,
        review_status: str = None,
        date_from: str = None,
        date_to: str = None,
    ) -> list[dict]:
        """Return recent incidents, newest first.

        date_from / date_to should be ISO date strings (YYYY-MM-DD or
        YYYY-MM-DDTHH:MM:SS).  date_to is treated as end-of-day inclusive.
        """
        clauses = []
        params = []
        if event_type and event_type in VALID_EVENT_TYPES:
            clauses.append("event_type = ?")
            params.append(event_type)
        if review_status and review_status in VALID_REVIEW_STATUSES:
            clauses.append("review_status = ?")
            params.append(review_status)
        if date_from:
            clauses.append("started_at >= ?")
            params.append(date_from[:10])
        if date_to:
            # Treat date_to as inclusive end-of-day
            params.append(date_to[:10] + "T23:59:59")
            clauses.append("started_at <= ?")

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT incident_id, case_id, device_id, event_type,
                       started_at, ended_at, duration_seconds,
                       peak_db, average_db, confidence, severity_score,
                       quiet_hours_violation, tenant_marked, review_status,
                       tamper_flags, retention_class, media_ref, detection_count
                FROM incidents
                {where}
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (*params, max(0, int(count))),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_incident(self, incident_id: str) -> dict | None:
        """Return a single incident by ID."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)
            ).fetchone()
        return dict(row) if row else None

    def update_incident(
        self,
        incident_id: str,
        review_status: str = None,
        tenant_marked: bool = None,
        case_id: str = None,
    ) -> bool:
        """Update mutable fields on an incident."""
        sets = []
        params = []
        if review_status is not None:
            if review_status not in VALID_REVIEW_STATUSES:
                return False
            sets.append("review_status = ?")
            params.append(review_status)
        if tenant_marked is not None:
            sets.append("tenant_marked = ?")
            params.append(1 if tenant_marked else 0)
        if case_id is not None:
            sets.append("case_id = ?")
            params.append(case_id)
        if not sets:
            return False

        params.append(incident_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE incidents SET {', '.join(sets)} WHERE incident_id = ?",
                params,
            )
            conn.commit()
            changed = conn.execute("SELECT changes()").fetchone()[0]
        return changed > 0
