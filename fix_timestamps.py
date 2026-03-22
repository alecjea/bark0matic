#!/usr/bin/env python3
"""
Rewrite detections.csv timestamps from UTC to local timezone.
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

TIMESTAMP_FORMATS = [
    "%Y-%m-%d %H:%M:%S %Z",
    "%Y-%m-%d %H:%M:%S UTC",
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
updated = 0
skipped = 0

with open(CSV_PATH, "r", newline="") as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames
    for row in reader:
        ts = row.get("timestamp", "")
        dt = parse_timestamp(ts)
        if dt:
            local_dt = dt.astimezone(LOCAL_TZ)
            row["timestamp"] = local_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
            updated += 1
        else:
            print(f"  Could not parse: {ts!r} — left unchanged")
            skipped += 1
        rows.append(row)

with open(CSV_PATH, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

print(f"Done. {updated} timestamps converted to {LOCAL_TZ_NAME}, {skipped} skipped.")
