#!/usr/bin/env python3
"""
Rewrite detections.csv: fix timestamps and add dog_size column.
Run once after changing your timezone setting.

Usage:
    python3 fix_timestamps.py
    python3 fix_timestamps.py Australia/Melbourne
"""
import sys
import csv
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

LOCAL_TZ_NAME = sys.argv[1] if len(sys.argv) > 1 else "Australia/Melbourne"
LOCAL_TZ = ZoneInfo(LOCAL_TZ_NAME)

CSV_PATH = os.path.join(os.path.dirname(__file__), "detections.csv")
BACKUP_PATH = CSV_PATH + ".bak"

NEW_HEADER = ["timestamp", "sound_type", "decibels", "frequency_hz", "confidence", "duration_seconds", "dog_size"]

TIMESTAMP_FORMATS = [
    "%Y-%m-%d %H:%M:%S %Z",
    "%Y-%m-%d %H:%M:%S UTC",
    "%Y-%m-%d %H:%M:%S AEST",
    "%Y-%m-%d %H:%M:%S AEDT",
    "%Y-%m-%d %H:%M:%S",
]

def parse_timestamp(ts):
    for fmt in TIMESTAMP_FORMATS:
        try:
            dt = datetime.strptime(ts.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None

def get_dog_size(sound_type, frequency_hz):
    """Return dog size based on frequency. Only for dog bark detections."""
    if sound_type and sound_type.lower() in ("dog bark", "dog"):
        try:
            freq = float(frequency_hz)
            return "Large dog" if freq < 2000 else "Small dog"
        except (ValueError, TypeError):
            pass
    return ""

if not os.path.exists(CSV_PATH):
    print(f"No CSV found at {CSV_PATH}")
    sys.exit(1)

# Backup first
with open(CSV_PATH, "r") as f:
    original = f.read()
with open(BACKUP_PATH, "w") as f:
    f.write(original)
print(f"Backup saved to {BACKUP_PATH}")

rows = []
ts_updated = 0
dog_updated = 0
skipped = 0

with open(CSV_PATH, "r", newline="") as f:
    reader = csv.DictReader(f)
    for row in reader:
        # Fix timestamp
        ts = row.get("timestamp", "")
        dt = parse_timestamp(ts)
        if dt:
            local_dt = dt.astimezone(LOCAL_TZ)
            row["timestamp"] = local_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
            ts_updated += 1
        else:
            print(f"  Could not parse: {ts!r} — left unchanged")
            skipped += 1

        # Add dog_size if missing or empty
        if not row.get("dog_size"):
            dog_size = get_dog_size(row.get("sound_type", ""), row.get("frequency_hz", ""))
            row["dog_size"] = dog_size
            if dog_size:
                dog_updated += 1

        rows.append(row)

with open(CSV_PATH, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=NEW_HEADER)
    writer.writeheader()
    writer.writerows(rows)

print(f"Done. {ts_updated} timestamps converted to {LOCAL_TZ_NAME}, {dog_updated} dog sizes added, {skipped} skipped.")
