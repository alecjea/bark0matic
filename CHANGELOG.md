# Changelog

All notable changes to Barkomatic are documented here.

## [1.0.24] - 2026-03-30

### Added
- Live camera snapshot card on the dashboard backed by the Raspberry Pi camera
- Saved JPEG snapshots linked from the detection log for recorded clips

### Changed
- When a selected sound saves an audio recording, Barkomatic now captures and stores a matching camera snapshot
- Snapshot filenames are now stored alongside audio filenames in SQLite
- Free disk space cleanup now removes old snapshots as well as old recordings and log rows
- Recording selection limit increased from 5 sounds to 10 sounds

## [1.0.23] - 2026-03-29

### Added
- Disk space safeguard that stops saving new audio recordings once disk usage reaches 95%
- `Free Disk Space` action in the dashboard that deletes recordings and SQLite log entries older than 30 days
- Live disk space status in the dashboard
- Footer link in the dashboard to open the changelog

### Changed
- Detection history chart removed from the dashboard
- Recording selection helper text now clearly explains multi-select and the need to save settings
- Selected recording sounds now appear as removable tags
- Detection log table now supports text filtering and recorded-only filtering, and CSV export respects the active filters
- Threshold sliders moved into the microphone card
- Recordings are only saved when the selected sound is the top detected match for that audio chunk
- Playback controls in the detections table were restyled for clearer play/stop/error states

### Fixed
- Recording selection now supports removing a chosen sound by clicking its tag
- Cleanup action now removes stale recordings and stale SQLite log rows together
- Detection log table no longer shows the dog-size column
- Human speech remains excluded from logged/recorded events while all other non-speech YAMNet matches are logged
- Recording settings UX now consistently reminds the user that changes are not applied until `Save All Settings` is pressed

## [1.0.13] - 2026-03-28

### Added
- Dashboard `Update Software` button that runs the existing GitHub update flow and waits for the service to come back online

### Changed
- Detection log storage moved from `detections.csv` to SQLite `detections.db`
- Dashboard CSV download now exports from SQLite on demand instead of reading a live CSV log file
- README and installer output updated to describe SQLite logging and CSV export behavior
- Detection now logs all non-speech YAMNet sounds above threshold instead of a single configured sound
- Dashboard recording settings now use a searchable YAMNet sound list and allow saving audio for up to 5 selected sounds

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
