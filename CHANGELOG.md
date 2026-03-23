# Changelog

All notable changes to Barkomatic are documented here.

## [1.0.0] - 2026-03-23

### Added
- Initial release: YAMNet TFLite-based AI sound detection for Raspberry Pi
- Flask web dashboard on port 8080
- Real-time detection log with newest-first ordering
- Detection history chart with 24h / week / month period selector (Chart.js)
- Audio recording on detection with in-browser WAV playback
- CSV event log with full JSON payload column (timestamp, dB, RMS energy, frequency, confidence, duration, dog size, YAMNet top-10 scores)
- SHA-256 hash verification for YAMNet model and class map files (supply-chain security)
- Configurable sound type, detection threshold, frequency range via web UI
- Australia/Melbourne timezone support with backfill of existing log timestamps
- ReSpeaker 2-Mic Pi HAT support (I2C + I2S + WM8960 overlay)
- Systemd service for auto-start on boot
- UFW firewall configuration (SSH port 22, dashboard port 8080)
- One-line install script (`bash install.sh`) for fresh Raspberry Pi setup
- Heuristic fallback classifier when TFLite runtime is unavailable
- Dog size estimation (large/small) based on detected frequency
- Live config reload without service restart
- Log clear and CSV download from dashboard

### Security
- YAMNet model files downloaded with SHA-256 verification; install aborts on hash mismatch
- Model loaded from local files only; no network access at runtime

### Dependencies
- numpy, sounddevice, ai-edge-litert, flask
- Removed librosa dependency (replaced with numpy-based resampling)
