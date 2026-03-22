#!/usr/bin/env python3
"""
Rewrite detections.csv: fix timestamps and add dog_size column.
Only converts timestamps that are NOT already in AEDT/AEST.

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

# Timezone abbreviations that mean "already local" — skip these
ALREADY_LOCAL = {"AEDT", "AEST"}

if not os.path.exists(CSV_PATH):
    print(f"No CSV found at {CSV_PATH}")
    sys.exit(1)

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
        ts = row.get("timestamp", "").strip()

        # Skip if already in local timezone
        already_local = any(ts.endswith(tz) for tz in ALREADY_LOCAL)

        if not already_local:
            try:
                clean = ts.replace(" UTC", "").strip()
                dt = datetime.strptime(clean, "%Y-%m-%d %H:%M:%S")
                dt = dt.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ)
                row["timestamp"] = dt.strftime("%Y-%m-%d %H:%M:%S %Z")
                ts_updated += 1
            except Exception:
                print(f"  Could not parse: {ts!r} — left unchanged")
                skipped += 1
        else:
            skipped += 1

        # Add dog_size if missing
        if not row.get("dog_size"):
            sound = row.get("sound_type", "").lower()
            if sound in ("dog bark", "dog"):
                try:
                    freq = float(row.get("frequency_hz", 0))
                    row["dog_size"] = "Large dog" if freq < 2000 else "Small dog"
                    dog_updated += 1
                except (ValueError, TypeError):
                    row["dog_size"] = ""
            else:
                row["dog_size"] = ""

        rows.append(row)

with open(CSV_PATH, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=NEW_HEADER)
    writer.writeheader()
    writer.writerows(rows)

print(f"Done. {ts_updated} timestamps converted, {dog_updated} dog sizes added, {skipped} already local/skipped.")
