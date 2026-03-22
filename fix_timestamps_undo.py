#!/usr/bin/env python3
"""
Fix double-converted timestamps by subtracting 11 hours,
and add dog_size column.
"""
import csv
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

CSV_PATH = os.path.join(os.path.dirname(__file__), "detections.csv")
BACKUP_PATH = CSV_PATH + ".bak2"
NEW_HEADER = ["timestamp", "sound_type", "decibels", "frequency_hz", "confidence", "duration_seconds", "dog_size"]
MELB = ZoneInfo("Australia/Melbourne")

if not os.path.exists(CSV_PATH):
    print("No CSV found")
    exit(1)

# Backup
with open(CSV_PATH, "r") as f:
    original = f.read()
with open(BACKUP_PATH, "w") as f:
    f.write(original)
print(f"Backup saved to {BACKUP_PATH}")

rows = []
fixed = 0

with open(CSV_PATH, "r", newline="") as f:
    reader = csv.DictReader(f)
    for row in reader:
        ts = row.get("timestamp", "")
        try:
            # Parse the AEDT timestamp as naive, subtract 11 hours
            clean = ts.replace(" AEDT", "").replace(" AEST", "").replace(" UTC", "").strip()
            dt = datetime.strptime(clean, "%Y-%m-%d %H:%M:%S")
            dt = dt - timedelta(hours=11)
            # Already in AEDT after subtraction, just label it
            row["timestamp"] = dt.strftime("%Y-%m-%d %H:%M:%S") + " AEDT"
            fixed += 1
        except Exception as e:
            print(f"  Skip: {ts!r} ({e})")

        # Add dog_size
        if not row.get("dog_size"):
            sound = row.get("sound_type", "").lower()
            if sound in ("dog bark", "dog"):
                try:
                    freq = float(row.get("frequency_hz", 0))
                    row["dog_size"] = "Large dog" if freq < 2000 else "Small dog"
                except (ValueError, TypeError):
                    row["dog_size"] = ""
            else:
                row["dog_size"] = ""

        rows.append(row)

with open(CSV_PATH, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=NEW_HEADER)
    writer.writeheader()
    writer.writerows(rows)

print(f"Fixed {fixed} timestamps (subtracted 11h double-conversion)")
