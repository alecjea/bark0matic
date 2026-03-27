# Changelog

All notable changes to Barkomatic are documented here.

## [1.0.13] - 2026-03-28

### Added
- Dashboard `Update Software` button that runs the existing GitHub update flow and waits for the service to come back online

### Changed
- Detection log storage moved from `detections.csv` to SQLite `detections.db`
- Dashboard CSV download now exports from SQLite on demand instead of reading a live CSV log file
- Legacy `detections.csv` data is imported into SQLite automatically on first run when the database is empty
- README and installer output updated to describe SQLite logging and CSV export behavior

## [1.0.11] - 2026-03-23

### Added
- Large/small dog frequency threshold slider on dashboard (configurable Hz cutoff)

### Fixed
- Installer: add `git` and `alsa-utils` to apt install (fresh installs were missing both)
- Installer: fail-fast architecture guard — aborts on 32-bit OS before pip install since ai-edge-litert requires arm64
- Installer: UFW allow rules (SSH + port 8080) now added before enabling firewall, preventing SSH lockout
- Installer: root user guard — refuses to run as root to avoid installing into /root
- Installer: consolidated duplicate ai-edge-litert install into single pip call

### Changed
- Moved CHANGELOG.md to project root
- Removed `/dev` directory and purged from git history

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
