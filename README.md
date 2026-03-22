# 🐕 Barkomatic

**Sound Detection & Logging System for Raspberry Pi**

Detect dog barks (or other sounds) on your Raspberry Pi using AI-powered audio classification, with a real-time web dashboard and CSV logging for evidence collection.

---

## Features

✅ **AI-Powered Detection** — Uses Google's YAMNet model (TensorFlow Lite) to classify 18 sound types with high accuracy

✅ **Web Dashboard** — Real-time status, settings control, detection logs, and built-in guide

✅ **Auto-Microphone Detection** — Automatically finds and tests USB audio devices

✅ **CSV Logging** — Timestamped detections with confidence scores for council complaints

✅ **Easy Deployment** — Single bash installer script (no Node.js required)

✅ **Auto-Start Service** — Systemd integration for automatic startup on boot

✅ **19 Sound Types** — Dog bark, cat meow, bird song, siren, fire alarm, glass breaking, gunshot, car horn, crying, screaming, thunder, knocking, snoring, coughing, engine, loud engine revving, alarm clock, speech, music

✅ **Adjustable Sensitivity** — Real-time sliders for confidence threshold, frequency range, energy level

✅ **Live Log Viewer** — See detections as they happen with download option

---

## Quick Start

### On Fresh Raspberry Pi (Easiest)

**One command to do everything:**
```bash
curl -fsSL https://raw.githubusercontent.com/alecjea/bark0matic/main/install.sh | bash
```

Or download and run:
```bash
git clone https://github.com/alecjea/bark0matic.git
cd bark0matic
bash install.sh
```

This will:
- ✅ Update system packages
- ✅ Install Python 3
- ✅ Configure UFW firewall (ports 22, 8080)
- ✅ Install all dependencies
- ✅ Setup systemd auto-start
- ✅ Start the service

Then open: `http://localhost:8080`

### Manual Setup

```bash
git clone https://github.com/alecjea/bark0matic.git
cd bark0matic
pip install --break-system-packages -r requirements.txt
python3 main.py
```

Open browser: `http://localhost:8080`

---

## Requirements

**On Raspberry Pi:**
- Raspberry Pi 3, 4, or 5 (any Linux system with Python 3.7+)
- USB microphone (or 3.5mm audio input)
- Python 3.7+ installed
- ~500MB free disk space
- Internet connection (for first-time dependency installation)

**Optional (for automated setup):**
- `bash` shell (standard on Linux)

---

## Installation

### On Raspberry Pi

**1. Clone the repository:**
```bash
git clone https://github.com/yourusername/barkomatic.git
cd barkomatic
```

**2. Create a virtual environment:**
```bash
python3 -m venv venv
source venv/bin/activate
```

**3. Install Python dependencies:**
```bash
pip install -r requirements.txt
```

**4. Run the app:**
```bash
python main.py
```

**5. Open dashboard in browser:**
```
http://localhost:8080
```

> **Note:** On Raspberry Pi OS, Python packages must be installed in a virtual environment (PEP 668). The `source venv/bin/activate` command activates it for your current terminal session.

### First Time Setup

On first run, the app will:
- Detect your USB microphone
- Create `config.json` with default settings
- Start the Flask web server

### Auto-Start on Boot (Optional)

For the app to start automatically when the Pi reboots:

```bash
bash install.sh
```

This creates a systemd service called `barkomatic` that auto-starts and auto-restarts if it crashes.

---

## Usage

### Web Dashboard

Access at `http://<rpi-ip>:8080`

**Features:**
- **Status Panel** — Detection status, sound type, detection count
- **Detection Log** — Live table with timestamp, confidence, decibels, frequency
- **Sound Type Selector** — Switch between 18 categories
- **Sensitivity Sliders** — Adjust detection threshold, frequency range, energy level
- **Download** — Export detections as CSV
- **Guide** — Click `?` for comprehensive help

### Command Line

Check status:
```bash
ssh pi@<rpi-ip> 'sudo systemctl status barkomatic'
```

View logs:
```bash
ssh pi@<rpi-ip> 'sudo journalctl -u barkomatic -f'
```

Download CSV:
```bash
scp pi@<rpi-ip>:~/barkomatic/detections.csv ./
```

---

## How It Works

### Detection Pipeline

1. **Audio Capture** — Records from USB microphone at 44.1kHz
2. **Feature Extraction** — Analyzes decibels, spectral centroid, zero-crossing rate, MFCCs
3. **YAMNet Classification** — TensorFlow Lite model returns confidence score
4. **Fallback** — Heuristic classifier if YAMNet unavailable
5. **CSV Logging** — Timestamped detections with metadata

### Sound Categories (19 Detection Types)

**Animal Sounds:**
1. 🐕 **Dog bark** — Barking, growling, howling
2. 🐱 **Cat meow** — Meowing, hissing, yowling
3. 🐦 **Bird song** — Chirping, singing, squawking

**Alarms & Sirens:**
4. 🚨 **Siren** — Emergency vehicle siren (police, ambulance, fire truck)
5. 🔔 **Smoke / fire alarm** — High-pitched alarm sound
6. ⏰ **Alarm clock** — Ringing alarm or beeping

**Vehicle Sounds:**
7. 🚗 **Car horn** — Honking, beeping
8. 🚗 **Engine / motor** — General engine sound
9. ⭐ **Loud engine revving** — Revving, acceleration, "vroom" sound

**Impact & Breaking:**
10. 🔨 **Glass breaking** — Shattering, smashing glass
11. 💥 **Gunshot** — Gunfire, shooting
12. ⚡ **Thunder** — Thunderclap, lightning rumble

**Human Sounds:**
13. 😢 **Crying / sobbing** — Crying, whimpering, wailing
14. 😱 **Screaming** — Loud screams, yelling
15. 🗣️ **Speech / talking** — Normal conversation, speaking
16. 🤧 **Coughing** — Cough, throat clearing
17. 😪 **Snoring** — Snoring, heavy breathing

**Other:**
18. 🎵 **Music** — Any music, instrumental, songs
19. 🚪 **Knocking** — Door knocking, tapping

---

## Project Structure

**Application Files:**
- `main.py` — Entry point (starts detection + web server)
- `sound_detector.py` — Detection engine (threading + control)
- `sound_classifier.py` — YAMNet AI classifier
- `audio_processor.py` — USB microphone capture
- `file_logger.py` — CSV logging
- `config.py` — Configuration management
- `web_server.py` — Flask web dashboard
- `requirements.txt` — Python dependencies

**Setup (Optional):**
- `install.sh` — Automated setup for auto-start on boot

**Documentation:**
- `README.md` — This file
- `QUICKSTART.md` — Quick reference guide
- `DEPLOYMENT.md` — Detailed troubleshooting
- `RELEASE_NOTES.md` — Version history

**Runtime Generated:**
- `config.json` — Settings (created on first run)
- `detections.csv` — Detection log (created by app)

---

## Python Dependencies

Installed automatically via `pip install -r requirements.txt`:

- **librosa** — Audio feature extraction
- **numpy** — Numerical computing
- **sounddevice** — Microphone capture
- **ai-edge-litert** — TensorFlow Lite inference
- **flask** — Web framework

No Node.js or JavaScript required!

---

## Configuration

Settings saved in `config.json`:

```json
{
  "sound_type_name": "Dog bark",
  "sound_type_indices": [69, 70, 75],
  "bark_detection_threshold": 0.3,
  "local_timezone": "Australia/Sydney",
  "rpi_microphone_device": "hw:1,0"
}
```

**Change via:**
1. Web dashboard → Advanced Settings
2. Direct edit: `nano ~/barkomatic/config.json`
3. Then restart: `sudo systemctl restart barkomatic`

---

## CSV Log Format

Detections saved to `detections.csv`:

```csv
timestamp,sound_type,decibels,frequency_hz,confidence,duration_seconds
2025-03-22T14:35:12+10:00,Dog bark,-45.2,850,0.92,2.3
2025-03-22T14:35:45+10:00,Dog bark,-42.8,920,0.88,1.8
```

Download from web dashboard for council complaints.

---

## Troubleshooting

### Service won't start
```bash
ssh pi@<rpi-ip> 'sudo journalctl -u barkomatic -n 50'
```

### Microphone not detected
```bash
ssh pi@<rpi-ip> arecord -l
# Update device in web dashboard
```

### No detections
- Lower confidence threshold (try 0.3-0.5)
- Lower energy threshold
- Ensure correct sound type selected
- Position microphone 30-60cm from sound

### False positives
- Increase confidence threshold (0.5-0.7)
- Increase energy threshold
- Adjust frequency range

**See DEPLOYMENT.md for detailed troubleshooting.**

---

## Performance

- **Supported:** Raspberry Pi 3+ or any Linux with Python 3.7+ and audio input
- **Detection latency:** ~100-200ms per 2-second audio chunk
- **Accuracy:** ~60-75% on AudioSet (depends on environment)
- **Disk:** ~500MB free required

---

## Security

- No credentials stored
- Web dashboard on `0.0.0.0:8080` (local network)
- Config file not sensitive
- SSH credentials only used during setup

For public networks, use reverse proxy (nginx) + authentication.

---

## Support

1. **In-app help** — Click `?` button on dashboard
2. **DEPLOYMENT.md** — Troubleshooting guide
3. **Web dashboard** — Real-time status and logs

---

## License

MIT License — Use freely for personal projects, council complaints, research, etc.

---

**Made for tracking dog barks (and other sounds) on Raspberry Pi.** 🐕📊
