# Barkomatic Quick Start

## 60-Second Setup

### 1. Download
Get `setup_allinone.sh` or clone the entire directory.

### 2. Run
```bash
chmod +x setup_allinone.sh
./setup_allinone.sh
```

### 3. Answer Prompts
- **RPI IP:** e.g., `192.168.1.100`
- **Username:** usually `pi`
- **Password:** your RPI password
- **Sound:** choose 1-18 (1 = Dog bark)
- **Timezone:** e.g., `Australia/Sydney`

### 4. Confirm
- SSH connection test
- Microphone detection
- System packages install
- Service startup

### 5. Access Dashboard
Open `http://<rpi-ip>:8080` in browser

---

## What Happens During Setup

```
✓ Test SSH connection
✓ Check system requirements (sudo, internet, audio, disk)
✓ Auto-detect USB microphone
✓ Test microphone with 1-second recording
✓ Install system packages (apt-get)
✓ Upload all Python files
✓ Create Python virtual environment
✓ Install Python dependencies (pip)
✓ Generate config.json
✓ Create systemd service
✓ Start detection service
✓ Show dashboard URL
```

---

## After Setup: You Have

✅ **Real-time detection** — Starts automatically on boot

✅ **Web dashboard** — View logs, adjust settings

✅ **CSV log file** — Download for evidence

✅ **Auto-restart** — Service restarts if it crashes

---

## Common Tasks

### View Detection Log
```bash
ssh pi@<rpi-ip> 'cat ~/barkomatic/detections.csv'
```

### Download CSV for Council
From web dashboard: Click **Download as CSV**

### Change Sound Type
Web dashboard → **Sound Type Selector** → pick new one → **Save**

### Check Service Status
```bash
ssh pi@<rpi-ip> 'sudo systemctl status barkomatic'
```

### View Live Logs
```bash
ssh pi@<rpi-ip> 'sudo journalctl -u barkomatic -f'
```

### Stop Service (temporarily)
```bash
ssh pi@<rpi-ip> 'sudo systemctl stop barkomatic'
```

### Restart Service
```bash
ssh pi@<rpi-ip> 'sudo systemctl restart barkomatic'
```

---

## Troubleshooting

### Can't SSH to RPI
- Check IP address: `ping <rpi-ip>`
- Verify SSH enabled: `raspi-config` → Interface Options → SSH
- Try password manually: `ssh pi@<rpi-ip>`

### Setup Script Fails at SSH
- Ensure SSH works first: `ssh pi@<rpi-ip> 'echo test'`
- Install `sshpass` for better experience
- Check username and password

### No Detections in Dashboard
1. Wait 10 seconds (takes time to initialize)
2. Make sounds near microphone
3. Check confidence not too high (try 0.3-0.5)
4. Verify correct sound type selected
5. Check service running: `sudo systemctl status barkomatic`

### Too Many False Positives
- Increase **Confidence Threshold** (slider to right)
- Increase **Energy Threshold** (slider to right)
- Narrow **Frequency Range**

### Microphone Issues
1. Check microphone plugged in
2. List devices: `arecord -l`
3. Update microphone in web dashboard

---

## Dashboard Features

### Top Bar
- **Status indicator** — Red = Stopped, Green = Running
- **Sound type** — Currently detecting (click to change)
- **?** button — In-app guide and help

### Detection Log
- **Live updates** — New detections appear in real-time
- **Columns** — Timestamp, Confidence, dB, Frequency, Duration
- **Download** — Export as CSV

### Advanced Settings (expand at bottom)
- **Confidence Threshold** — Higher = stricter
- **Frequency Range** — Hz range for target sound
- **Energy Threshold** — dB threshold
- **Chunk Size** — Analysis window (seconds)

---

## 18 Sound Types Available

| # | Sound | Use Case |
|---|-------|----------|
| 1 | Dog bark | Neighbor's dog |
| 2 | Cat meow | Cat complaints |
| 3 | Bird song | Bird noise |
| 4 | Siren | Emergency vehicles |
| 5 | Fire alarm | Alarm testing |
| 6 | Glass breaking | Safety monitoring |
| 7 | Gunshot | Firearm discharge |
| 8 | Car horn | Traffic noise |
| 9 | Crying / sobbing | Distress sounds |
| 10 | Screaming | Loud vocalizations |
| 11 | Thunder | Weather events |
| 12 | Knocking | Door impacts |
| 13 | Snoring | Sleep sounds |
| 14 | Coughing | Illness sounds |
| 15 | Engine / motor | Vehicle noise |
| 16 | Alarm clock | Electronic alarms |
| 17 | Speech / talking | Voice detection |
| 18 | Music | Musical sounds |

---

## File Locations (on RPI)

```
/home/pi/barkomatic/
├── config.json              — Configuration (edit via dashboard)
├── detections.csv          — Detection log (download from dashboard)
├── main.py                 — Entry point
├── sound_detector.py       — Detection engine
├── sound_classifier.py     — AI classifier
├── audio_processor.py      — Microphone
├── file_logger.py          — CSV logging
├── config.py               — Config management
├── web_server.py           — Web UI
├── requirements.txt        — Dependencies
├── venv/                   — Python virtual environment
└── barkomatic.service      — Systemd service
```

---

## Getting Help

1. **In-app guide** — Click `?` in dashboard header
2. **DEPLOYMENT.md** — Full troubleshooting guide
3. **Web dashboard** — Real-time status and logs
4. **Systemd logs** — `journalctl -u barkomatic`

---

## For Council Complaints

### Prepare Evidence

1. **Collect data** — Use dashboard to monitor for 7-14 days
2. **Download CSV** — Click "Download as CSV" button
3. **Open in Excel** — Review timestamps and confidence scores
4. **Screenshot dashboard** — Show confidence scores visually
5. **Note high-confidence detections** — Focus on detections > 0.80 confidence

### What to Include

- CSV file with timestamps, confidence scores, decibels
- Screenshots of detection log
- Notes about time of day, circumstances
- Multiple incidents across different days

### Tips

- High confidence (0.85+) = stronger evidence
- Multiple detections on same date = pattern
- Decibels show loudness (compare to reference sounds)
- Frequency data shows it's not other animals

---

**Total setup time: ~5-10 minutes**

**Start detecting immediately after dashboard loads!**

🐕 Happy detecting!
