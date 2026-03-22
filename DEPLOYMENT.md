# Barkomatic Deployment Guide

## Quick Start

Barkomatic can be deployed to a Raspberry Pi using either method:

### Method 1: All-in-One Script (Recommended for simplicity)

This is the simplest approach - a single self-contained bash script with everything embedded.

**Requirements:**
- SSH access to your Raspberry Pi
- `sshpass` (optional, for automated password entry)

**Steps:**
1. Download `setup_allinone.sh` to your computer
2. Make it executable:
   ```bash
   chmod +x setup_allinone.sh
   ```
3. Run it:
   ```bash
   ./setup_allinone.sh
   ```
4. Answer the interactive prompts:
   - Raspberry Pi IP address
   - Username (default: `pi`)
   - Password
   - Sound type to detect (1-18 options)
   - Timezone
5. Confirm at each key step
6. Once complete, access the web dashboard at `http://<rpi-ip>:8080`

**What it does:**
- Tests SSH connection
- Checks system prerequisites (sudo, internet, audio group, disk space)
- Auto-detects USB microphone
- Installs system packages
- Deploys all Python files (decoded from embedded base64)
- Creates Python virtual environment
- Installs dependencies via pip
- Generates `config.json`
- Creates systemd service for auto-start
- Starts the detection service

**File size:** ~98 KB (includes all Python code)

---

### Method 2: Setup Script + Python Files (More flexibility)

If you prefer to keep the Python files separate (for development or customization):

**Requirements:**
- All files in the same directory:
  - `setup.sh`
  - `main.py`, `sound_detector.py`, `sound_classifier.py`, etc.
  - `requirements.txt`
- SSH access to Raspberry Pi
- `sshpass` (optional)

**Steps:**
1. Download or clone the entire `barkomatic` directory
2. Make setup.sh executable:
   ```bash
   chmod +x setup.sh
   ```
3. Run it:
   ```bash
   ./setup.sh
   ```
4. Follow the same interactive prompts as Method 1

**Benefits:**
- Easier to modify Python files before deployment
- Can review actual source code before deploying
- Smaller compressed archive if distributing

---

## What Gets Installed on the Raspberry Pi

After running either setup script, your RPI will have:

```
/home/pi/barkomatic/
├── main.py                          # Entry point
├── sound_detector.py                # Detection engine
├── sound_classifier.py              # YAMNet AI classifier
├── audio_processor.py               # Microphone capture
├── file_logger.py                   # CSV logging
├── config.py                        # Configuration management
├── web_server.py                    # Flask web UI
├── requirements.txt                 # Python dependencies
├── config.json                      # Generated config file
├── detections.csv                   # Detection log
├── venv/                            # Python virtual environment
└── barkomatic.service               # Systemd service file
```

### System Service

The `barkomatic` service is registered with systemd and will:
- Start automatically on boot
- Restart automatically if it crashes
- Run in the background
- Output logs to the system journal

**Common commands:**
```bash
# Check status
ssh pi@<rpi-ip> 'sudo systemctl status barkomatic'

# View logs
ssh pi@<rpi-ip> 'sudo journalctl -u barkomatic -n 100 -f'

# Stop service
ssh pi@<rpi-ip> 'sudo systemctl stop barkomatic'

# Restart service
ssh pi@<rpi-ip> 'sudo systemctl restart barkomatic'
```

---

## Web Dashboard

Once deployed, access the web dashboard at:
```
http://<raspberry-pi-ip>:8080
```

### Features

**Status Panel**
- Real-time detection status
- Microphone name and device
- Current sound type being monitored
- Service running/stopped indicator

**Detection Log**
- Live table of detected sounds
- Timestamp, confidence score, decibels, frequency
- Download CSV for evidence/complaints

**Sound Type Selector**
- Switch between 18 different sound categories
- Options: Dog bark, Cat meow, Bird song, Siren, Fire alarm, Glass breaking, Gunshot, Car horn, Crying, Screaming, Thunder, Knocking, Snoring, Coughing, Engine/motor, Alarm clock, Speech, Music

**Sensitivity Settings**
- Confidence threshold (0.0 - 1.0)
- Frequency range detection
- Energy threshold (decibels)
- Chunk size for analysis
- All changes saved automatically

**Guide & Help**
- Click the `?` button in the header for comprehensive guide
- Learn how YAMNet AI detection works
- Understanding confidence scores
- Tips for positioning the microphone
- How to interpret the detection log

---

## Microphone Setup

### Auto-Detection

The setup script automatically detects your USB microphone by:
1. Running `arecord -l` to list audio devices
2. Looking in `/proc/asound/cards` for USB audio
3. Preferring USB devices over built-in audio

### Manual Configuration

If auto-detection fails or detects the wrong device, you can change it in the web dashboard:
1. Go to **Advanced Settings** (expand at bottom)
2. Modify **Microphone Device** (format: `hw:card,device`, e.g., `hw:1,0`)
3. Click **Save Settings**

---

## Sound Detection Types

The system can detect and distinguish between 18 different sound categories using YAMNet, Google's pre-trained audio classification AI:

1. **Dog bark** — Canine barking (primary use case)
2. **Cat meow** — Feline vocalizations
3. **Bird song** — Avian sounds
4. **Siren** — Emergency vehicle sirens
5. **Smoke/Fire alarm** — Alarm notifications
6. **Glass breaking** — Shattering glass
7. **Gunshot** — Firearm discharge
8. **Car horn** — Vehicle honking
9. **Crying/Sobbing** — Human distress
10. **Screaming** — Loud vocalizations
11. **Thunder** — Electrical storms
12. **Knocking** — Door/object impacts
13. **Snoring** — Sleep vocalization
14. **Coughing** — Respiratory sounds
15. **Engine/Motor** — Vehicle/machinery
16. **Alarm clock** — Electronic alarms
17. **Speech/Talking** — General voices
18. **Music** — Musical sounds

Each category uses carefully selected YAMNet audio class indices to maximize accuracy.

---

## Logging & Data Export

### CSV Format

Detections are logged to `detections.csv` on the RPI:

```csv
timestamp,sound_type,decibels,frequency_hz,confidence,duration_seconds
2025-03-22T14:35:12+10:00,Dog bark,-45.2,850,0.92,2.3
2025-03-22T14:35:45+10:00,Dog bark,-42.8,920,0.88,1.8
```

### Downloading Detections

1. Open the web dashboard at `http://<rpi-ip>:8080`
2. Scroll to **Detection Log**
3. Click **Download as CSV**
4. Open in Excel, Google Sheets, or your preferred tool

### For Council Complaints

The CSV data can be used as evidence:
- **Timestamp** — Exact date and time of detection
- **Confidence** — How certain the AI is (0.0-1.0)
- **Duration** — How long the sound lasted
- **Decibels** — Sound intensity (loudness)
- **Frequency** — Characteristic frequency (Hz)

This data can support complaints to local councils about noise violations.

---

## Troubleshooting

### Service Not Starting

Check the logs:
```bash
ssh pi@<rpi-ip> 'sudo journalctl -u barkomatic -n 50'
```

### Microphone Not Detected

1. SSH into the RPI:
   ```bash
   ssh pi@<rpi-ip>
   ```
2. List available audio devices:
   ```bash
   arecord -l
   ```
3. Update the config in the web dashboard with the correct device

### No Detections

1. Check microphone positioning — should be 30-60cm from the sound source
2. Adjust sensitivity:
   - Lower **Confidence Threshold** for more detections
   - Lower **Energy Threshold** for quieter sounds
3. Verify correct **Sound Type** is selected

### High False Positives

1. Increase **Confidence Threshold** (0.5-0.7 recommended)
2. Increase **Energy Threshold** to filter out background noise
3. Adjust **Frequency Range** to match your target sound

### SSH Connection Issues

- Verify RPI IP address is correct: `ping <rpi-ip>`
- Ensure SSH is enabled: `sudo raspi-config` → Interface Options → SSH
- Check username and password are correct
- Try `ssh pi@<rpi-ip> "echo test"` manually

---

## Security Notes

- **Credentials:** Not stored anywhere. Setup prompts for SSH credentials once.
- **Network:** Web dashboard runs on `0.0.0.0:8080` (accessible from network)
- **Firewall:** Setup script automatically opens port 8080 if UFW is active
- **Config:** Saved locally on RPI as `config.json`

If deploying to a public network, consider:
- Using a reverse proxy (nginx) with authentication
- Restricting port 8080 to local network only
- Running behind a firewall

---

## Development & Customization

If you used the regular `setup.sh` (not all-in-one), you can modify the Python files before deployment:

1. Edit any Python file locally
2. Run `setup.sh` again to redeploy (it will overwrite)
3. Service will restart automatically

### Key Files to Customize

- **sound_classifier.py** — Change YAMNet indices for different sound types
- **config.py** — Add new configuration parameters
- **web_server.py** — Modify web UI layout, add new API endpoints
- **audio_processor.py** — Change microphone settings, audio processing

---

## Uninstalling

To remove Barkomatic from your Raspberry Pi:

```bash
ssh pi@<rpi-ip> << 'EOF'
sudo systemctl stop barkomatic
sudo systemctl disable barkomatic
sudo rm /etc/systemd/system/barkomatic.service
sudo systemctl daemon-reload
rm -rf ~/barkomatic
EOF
```

---

## Next Steps

1. **Run the installer:** `./setup_allinone.sh` (or `./setup.sh`)
2. **Access the dashboard:** `http://<rpi-ip>:8080`
3. **Click the `?` button** for in-app guidance
4. **Adjust sensitivity settings** based on your environment
5. **Download detection logs** when needed for complaints

Happy detecting! 🐕
