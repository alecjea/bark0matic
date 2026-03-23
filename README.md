# Bark0matic

**AI Sound Detection & Logging for Raspberry Pi**

Detects sounds (dog barks, music, sirens, and more) through a USB microphone using Google's YAMNet AI model. Logs detections with timestamps and confidence scores to CSV. Controlled via a real-time web dashboard.

<img width="711" height="964" alt="image" src="https://github.com/user-attachments/assets/4d38e77d-3775-427e-820d-a40bff61fe6b" />


---

## Features

- **AI Detection** — Google YAMNet (TensorFlow Lite), 521 AudioSet classes, runs fully offline
- **19 Sound Types** — Dog bark, cat, bird, siren, fire alarm, glass breaking, gunshot, car horn, engine, crying, screaming, thunder, knocking, snoring, coughing, alarm clock, speech, music, and more
- **Web Dashboard** — Real-time status, settings, detection log, clear log button, CSV download
- **Detection History Chart** — 24h/week/month bar chart showing detection patterns over time
- **Dog Size Detection** — Estimates large vs small dog based on bark frequency (< 2000Hz = large)
- **Audio Playback** — Every detection saves a WAV clip you can play back from the dashboard
- **USB Mic Auto-Detection** — Detect, test, and save microphone via dashboard
- **CSV Logging** — Timestamped detections with confidence, dB, frequency, and dog size
- **Timezone Support** — Configurable local timezone for accurate timestamps
- **Systemd Service** — Auto-starts on boot, auto-restarts on crash
- **Adjustable Sensitivity** — Confidence threshold (0.01–1.0), energy threshold, frequency range

<img width="793" height="742" alt="image" src="https://github.com/user-attachments/assets/fef814d9-1899-41b7-81ac-fc63893831df" />

---

## Quick Install (Fresh Raspberry Pi)

> **Requires Raspberry Pi OS 64-bit (arm64).** The AI/YAMNet runtime (`ai-edge-litert`) only publishes 64-bit wheels. The installer will detect 32-bit OS and exit with a clear message before anything is installed. Use the [Raspberry Pi Imager](https://www.raspberrypi.com/software/) and choose **Raspberry Pi OS (64-bit)**.

**One line:**
```bash
curl -fsSL https://raw.githubusercontent.com/alecjea/bark0matic/master/install.sh | bash
```

**Or clone and run:**
```bash
git clone -b master https://github.com/alecjea/bark0matic.git
cd bark0matic
bash install.sh
```

Then open: `http://<rpi-ip>:8080`

The installer:
- Checks architecture — exits immediately on non-arm64 with instructions to switch to 64-bit OS
- Installs git, Python 3, pip, and audio libraries (ALSA/arecord)
- Configures UFW firewall (ports 22 and 8080)
- Installs Python dependencies including the YAMNet TFLite runtime
- Downloads and SHA-256 verifies the YAMNet model files
- Creates and starts a systemd service (auto-start on boot)

---

## Updating

```bash
cd ~/bark0matic
bash update.sh
```

Pulls latest from master and restarts the service.

---

## Requirements

- Raspberry Pi 3, 4, or 5 running **Raspberry Pi OS 64-bit (arm64)**
- USB microphone (or ReSpeaker 2-Mic Pi HAT)
- ~500MB free disk space
- Internet connection for initial install

---

## How It Works

1. **Audio Capture** — Records 2-second chunks via `arecord` using ALSA (`plughw` for hardware resampling to 16kHz)
2. **YAMNet Classification** — TFLite model scores each chunk against 521 sound classes
3. **Threshold Check** — If confidence >= threshold, logs the detection
4. **CSV + Dashboard** — Detection logged to `detections.csv` and shown live in the web UI

Audio is captured using `plughw:X,Y` so ALSA resamples to 16kHz regardless of what the USB mic natively supports.

---

## Web Dashboard

Access at `http://<rpi-ip>:8080`

- **Status** — Running/stopped indicator with pulsing dot, detection count, uptime
- **Detection History** — Bar chart with 24h/week/month toggle to spot patterns
- **Sound Type** — Switch between 19 categories
- **Microphone** — Detect, test, and save USB input device
- **Sensitivity** — Confidence threshold (0.01-1.0), energy threshold sliders
- **Detection Log** — Live table with play button, dog size, clear log, CSV download
- **Guide** — Click ? for help on all settings

---

## Configuration

Settings saved to `config.json` (auto-created, not tracked in git):

```json
{
  "sound_type_name": "Dog bark",
  "sound_type_indices": [69, 70, 75],
  "rpi_microphone_device": "hw:2,0",
  "rpi_microphone_rate": 16000,
  "bark_detection_threshold": 0.05,
  "bark_detection_energy_threshold": -70.0,
  "local_timezone": "Australia/Melbourne"
}
```

Change via the web dashboard or edit directly, then restart:
```bash
sudo systemctl restart barkomatic
```

---

## Sound Categories

| Category | Description |
|---|---|
| Dog bark | Barking, growling, howling |
| Cat meow | Meowing, hissing, yowling |
| Bird song | Chirping, singing |
| Siren | Emergency vehicle |
| Smoke / fire alarm | High-pitched alarm |
| Glass breaking | Shattering |
| Gunshot | Gunfire |
| Car horn | Honking |
| Engine / motor | General engine |
| Loud engine revving | Revving, acceleration |
| Alarm clock | Ringing, beeping |
| Crying / sobbing | Crying, wailing |
| Screaming | Loud screams |
| Speech / talking | Conversation |
| Coughing | Cough, throat clearing |
| Snoring | Snoring |
| Thunder | Thunderclap |
| Knocking | Door knock, tapping |
| Music | Any music |

---

## Troubleshooting

**Service won't start:**
```bash
sudo journalctl -u barkomatic -n 50 --no-pager
```

**No microphone found:**
```bash
arecord -l
```
Then set the device in the web dashboard (e.g. `hw:2,0`).

**No detections:**
- Lower confidence threshold (try 0.03-0.05)
- Lower energy threshold (try -70dB)
- Make sure correct sound type is selected
- Move mic closer to sound source

**Too many false positives:**
- Raise confidence threshold (0.3+)
- Raise energy threshold

---

## Project Files

| File | Purpose |
|---|---|
| `main.py` | Entry point |
| `sound_detector.py` | Detection loop (threading) |
| `sound_classifier.py` | YAMNet TFLite inference |
| `audio_processor.py` | arecord capture + feature extraction |
| `file_logger.py` | CSV logging |
| `config.py` | Config load/save |
| `web_server.py` | Flask dashboard |
| `install.sh` | Fresh install script |
| `update.sh` | Pull + restart script |

---

## License

MIT
