"""Flask web interface for bark0matic."""
import os
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, send_file, render_template_string
from config import Config

# Will be set by main.py
detector = None

# Sound categories (mirrored from setup_allinone.sh for the web UI)
SOUND_CATEGORIES = [
    {"name": "Dog bark", "indices": [69, 70, 75]},
    {"name": "Cat meow", "indices": [76, 78]},
    {"name": "Bird song", "indices": [106, 107]},
    {"name": "Siren (emergency vehicle)", "indices": [316, 317, 318, 319]},
    {"name": "Smoke / fire alarm", "indices": [393, 394]},
    {"name": "Glass breaking", "indices": [435]},
    {"name": "Gunshot", "indices": [421]},
    {"name": "Car horn / honking", "indices": [302, 312]},
    {"name": "Crying / sobbing", "indices": [19, 20]},
    {"name": "Screaming", "indices": [11]},
    {"name": "Thunder", "indices": [281]},
    {"name": "Knocking", "indices": [353]},
    {"name": "Snoring", "indices": [38]},
    {"name": "Coughing", "indices": [42]},
    {"name": "Engine / motor", "indices": [337]},
    {"name": "Loud engine revving", "indices": [337, 343, 347]},
    {"name": "Alarm clock", "indices": [390]},
    {"name": "Speech / talking", "indices": [0]},
    {"name": "Music", "indices": [132, 249]},
]


def create_app(sound_detector):
    """Create Flask app with reference to the detector."""
    global detector
    detector = sound_detector

    app = Flask(__name__)

    @app.route("/")
    def dashboard():
        return render_template_string(DASHBOARD_HTML)

    @app.route("/api/status")
    def api_status():
        return jsonify(detector.get_status())

    @app.route("/api/detections")
    def api_detections():
        count = request.args.get("count", 100, type=int)
        rows = detector.logger.get_recent(count)
        return jsonify(rows)

    @app.route("/api/settings", methods=["GET"])
    def api_get_settings():
        data = Config.to_dict()
        data["sound_categories"] = SOUND_CATEGORIES
        return jsonify(data)

    @app.route("/api/settings", methods=["POST"])
    def api_save_settings():
        data = request.json
        if "local_timezone" in data:
            Config.LOCAL_TIMEZONE = data["local_timezone"]
        if "threshold" in data:
            Config.BARK_DETECTION_THRESHOLD = float(data["threshold"])
        if "min_frequency" in data:
            Config.BARK_DETECTION_MIN_FREQUENCY = float(data["min_frequency"])
        if "max_frequency" in data:
            Config.BARK_DETECTION_MAX_FREQUENCY = float(data["max_frequency"])
        if "energy_threshold" in data:
            Config.BARK_DETECTION_ENERGY_THRESHOLD = float(data["energy_threshold"])
        if "chunk_size" in data:
            Config.BARK_DETECTION_CHUNK_SIZE = float(data["chunk_size"])
        if "dog_size_frequency_threshold" in data:
            Config.DOG_SIZE_FREQUENCY_THRESHOLD = int(data["dog_size_frequency_threshold"])
        if "sound_type_name" in data:
            Config.SOUND_TYPE_NAME = data["sound_type_name"]
            # Find matching indices
            for cat in SOUND_CATEGORIES:
                if cat["name"] == data["sound_type_name"]:
                    Config.SOUND_TYPE_INDICES = cat["indices"]
                    break

        Config.save()
        detector.reload_config()
        return jsonify({"status": "ok"})

    @app.route("/api/control", methods=["POST"])
    def api_control():
        data = request.json
        action = data.get("action")
        if action == "start":
            detector.start()
            return jsonify({"status": "started"})
        elif action == "stop":
            detector.stop()
            return jsonify({"status": "stopped"})
        return jsonify({"error": "invalid action"}), 400

    @app.route("/api/clear-log", methods=["POST"])
    def api_clear_log():
        try:
            detector.logger.clear()
            return jsonify({"status": "ok"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route("/api/download")
    def api_download():
        csv_path = detector.logger.get_csv_path()
        return send_file(csv_path, as_attachment=True, download_name="detections.csv")

    @app.route("/api/audio/<filename>")
    def api_audio(filename):
        """Serve a recorded audio clip for playback."""
        audio_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recordings")
        filepath = os.path.join(audio_dir, filename)
        if not os.path.exists(filepath):
            return jsonify({"error": "not found"}), 404
        return send_file(filepath, mimetype="audio/wav")

    @app.route("/api/chart-data")
    def api_chart_data():
        """Return detection counts bucketed by period: 24h (hourly), week (daily), month (daily)."""
        period = request.args.get("period", "24h")
        try:
            tz = Config.get_timezone()
            now = datetime.now(tz)
            rows = detector.logger.get_recent(50000)

            def parse_ts(ts_str):
                for fmt in ("%Y-%m-%d %H:%M:%S %Z", "%Y-%m-%d %H:%M:%S"):
                    try:
                        return datetime.strptime(ts_str.strip(), fmt)
                    except ValueError:
                        continue
                return None

            if period == "week":
                n_buckets = 7
                buckets = {}
                for i in range(n_buckets):
                    d = now - timedelta(days=n_buckets - 1 - i)
                    key = d.strftime("%Y-%m-%d")
                    buckets[key] = 0
                for row in rows:
                    ts = parse_ts(row.get("timestamp", ""))
                    if ts:
                        key = ts.strftime("%Y-%m-%d")
                        if key in buckets:
                            buckets[key] += 1
                labels = []
                counts = []
                for i in range(n_buckets):
                    d = now - timedelta(days=n_buckets - 1 - i)
                    key = d.strftime("%Y-%m-%d")
                    labels.append(d.strftime("%a %d"))
                    counts.append(buckets.get(key, 0))

            elif period == "month":
                n_buckets = 30
                buckets = {}
                for i in range(n_buckets):
                    d = now - timedelta(days=n_buckets - 1 - i)
                    key = d.strftime("%Y-%m-%d")
                    buckets[key] = 0
                for row in rows:
                    ts = parse_ts(row.get("timestamp", ""))
                    if ts:
                        key = ts.strftime("%Y-%m-%d")
                        if key in buckets:
                            buckets[key] += 1
                labels = []
                counts = []
                for i in range(n_buckets):
                    d = now - timedelta(days=n_buckets - 1 - i)
                    key = d.strftime("%Y-%m-%d")
                    labels.append(d.strftime("%d/%m"))
                    counts.append(buckets.get(key, 0))

            else:  # 24h default
                n_buckets = 24
                buckets = {}
                for i in range(n_buckets):
                    h = now - timedelta(hours=n_buckets - 1 - i)
                    key = h.strftime("%Y-%m-%d %H")
                    buckets[key] = 0
                for row in rows:
                    ts = parse_ts(row.get("timestamp", ""))
                    if ts:
                        key = ts.strftime("%Y-%m-%d %H")
                        if key in buckets:
                            buckets[key] += 1
                labels = []
                counts = []
                for i in range(n_buckets):
                    h = now - timedelta(hours=n_buckets - 1 - i)
                    key = h.strftime("%Y-%m-%d %H")
                    labels.append(h.strftime("%-I%p").lower())
                    counts.append(buckets.get(key, 0))

            return jsonify({"labels": labels, "counts": counts, "period": period})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/detect-microphone")
    def api_detect_microphone():
        """Detect available audio input devices."""
        try:
            import subprocess

            devices = []

            # Detect via arecord (Linux) - gives card numbers
            try:
                result = subprocess.run(['arecord', '-l'], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    import re
                    for line in result.stdout.split('\n'):
                        m = re.match(r'card (\d+):.*\[(.+?)\].*device (\d+):', line)
                        if m:
                            card, name, dev = m.group(1), m.group(2).strip(), m.group(3)
                            devices.append({
                                "id": f"hw:{card},{dev}",
                                "name": name,
                                "label": f"hw:{card},{dev} - {name}"
                            })
            except:
                pass

            # Fallback: sounddevice library
            if not devices:
                import sounddevice as sd
                sd_devices = sd.query_devices()
                for i, device in enumerate(sd_devices):
                    if device['max_input_channels'] > 0:
                        devices.append({
                            "id": device['name'],
                            "name": device['name'],
                            "label": f"{device['name']}"
                        })

            return jsonify({
                "status": "ok",
                "devices": devices,
                "current": Config.RPI_MICROPHONE_DEVICE
            })
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route("/api/test-microphone")
    def api_test_microphone():
        """Test microphone by recording 2 seconds of audio."""
        device = request.args.get("device", Config.RPI_MICROPHONE_DEVICE)
        try:
            import sounddevice as sd
            import numpy as np
            import time

            SAMPLE_RATE = 44100
            DURATION = 2

            # Stop detector to free the mic
            was_running = detector.running
            if was_running:
                detector.stop()
                time.sleep(1)

            print(f"[MIC] Testing device: {device}")
            try:
                audio = sd.rec(int(SAMPLE_RATE * DURATION), samplerate=SAMPLE_RATE,
                              channels=1, dtype=np.float32, device=device)
                sd.wait()
            finally:
                # Restart detector if it was running
                if was_running:
                    detector.start()

            rms_energy = np.sqrt(np.mean(audio**2))
            peak = np.max(np.abs(audio))
            db = 20 * np.log10(rms_energy + 1e-10)

            if rms_energy < 0.001:
                return jsonify({
                    "status": "warning",
                    "message": "Device found but very low audio. Check mic connection.",
                    "db": round(float(db), 1)
                })

            return jsonify({
                "status": "ok",
                "message": f"Microphone working! {round(float(db), 1)}dB",
                "db": round(float(db), 1),
                "peak": round(float(peak * 100), 1)
            })
        except Exception as e:
            # Make sure detector restarts even on error
            if detector and not detector.running:
                detector.start()
            return jsonify({
                "status": "error",
                "message": f"Test failed: {str(e)}"
            }), 500

    @app.route("/api/save-microphone", methods=["POST"])
    def api_save_microphone():
        """Save selected microphone device."""
        data = request.json
        device = data.get("device")
        if device:
            Config.RPI_MICROPHONE_DEVICE = device
            Config.save()
            detector.reload_config()
            return jsonify({"status": "ok", "device": device})
        return jsonify({"status": "error", "message": "No device specified"}), 400

    return app


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>bark0matic</title>
<style>
  :root {
    --bg-dark: #0b1120;
    --bg-card: #151d2e;
    --bg-input: #0b1120;
    --border: #1e2d45;
    --border-focus: #38bdf8;
    --text: #e2e8f0;
    --text-dim: #64748b;
    --text-label: #94a3b8;
    --accent: #38bdf8;
    --green: #4ade80;
    --green-bg: rgba(74, 222, 128, 0.1);
    --red: #f87171;
    --red-bg: rgba(248, 113, 113, 0.1);
    --blue: #60a5fa;
    --purple: #a78bfa;
    --orange: #fb923c;
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: var(--bg-dark);
    color: var(--text);
    min-height: 100vh;
  }

  /* ── Header ─────────────────────────────────────────── */
  .header {
    background: linear-gradient(135deg, #0f172a 0%, #1a1f3a 100%);
    border-bottom: 1px solid var(--border);
    padding: 20px 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .header h1 {
    font-size: 1.5rem;
    font-weight: 700;
    background: linear-gradient(135deg, var(--accent), var(--purple));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .header-badge {
    font-size: 0.7rem;
    background: var(--accent);
    color: var(--bg-dark);
    padding: 2px 8px;
    border-radius: 10px;
    font-weight: 600;
    -webkit-text-fill-color: var(--bg-dark);
  }

  /* ── Layout ─────────────────────────────────────────── */
  .container { max-width: 1100px; margin: 0 auto; padding: 20px; }
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }

  /* ── Cards ──────────────────────────────────────────── */
  .card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 16px;
  }
  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 16px;
  }
  .card-header h2 {
    font-size: 0.85rem;
    color: var(--text-label);
    text-transform: uppercase;
    letter-spacing: 1.5px;
    font-weight: 600;
  }

  /* ── Status Bar ─────────────────────────────────────── */
  .status-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px;
    margin-bottom: 16px;
  }
  .stat {
    background: var(--bg-dark);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 16px;
  }
  .stat-label {
    font-size: 0.7rem;
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 6px;
  }
  .stat-value {
    font-size: 1.5rem;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
  }
  .stat-value.running { color: var(--green); }
  .stat-value.stopped { color: var(--red); }

  /* ── Pulse dot ──────────────────────────────────────── */
  .pulse-dot {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    margin-right: 8px;
    vertical-align: middle;
    flex-shrink: 0;
  }
  .pulse-dot.running {
    background: var(--green);
    box-shadow: 0 0 0 0 rgba(74,222,128,0.6);
    animation: pulse 1.6s infinite;
  }
  .pulse-dot.stopped {
    background: var(--red);
    animation: none;
  }
  @keyframes pulse {
    0%   { box-shadow: 0 0 0 0 rgba(74,222,128,0.6); }
    70%  { box-shadow: 0 0 0 8px rgba(74,222,128,0); }
    100% { box-shadow: 0 0 0 0 rgba(74,222,128,0); }
  }

  /* ── Buttons ────────────────────────────────────────── */
  .controls { display: flex; gap: 10px; flex-wrap: wrap; }
  button {
    padding: 10px 20px;
    border: none;
    border-radius: 8px;
    font-size: 0.85rem;
    cursor: pointer;
    font-weight: 600;
    transition: all 0.15s;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  button:hover { transform: translateY(-1px); filter: brightness(1.1); }
  button:active { transform: translateY(0); }
  .btn-start { background: var(--green); color: #000; }
  .btn-stop { background: var(--red); color: #fff; }
  .btn-download { background: var(--blue); color: #000; }
  .btn-save { background: var(--purple); color: #fff; }
  .btn-clear { background: transparent; border: 1px solid var(--border); color: var(--text-dim); }
  .chart-period { background: transparent; border: 1px solid var(--border); color: var(--text-dim); padding: 4px 10px; border-radius: 6px; cursor: pointer; font-size: 0.75rem; }
  .chart-period.active { background: var(--orange); color: #000; border-color: var(--orange); font-weight: 600; }
  .chart-period:hover:not(.active) { border-color: var(--text-dim); color: var(--text); }

  /* ── Form Fields ────────────────────────────────────── */
  .settings-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 14px;
    margin-bottom: 16px;
  }
  .field { display: flex; flex-direction: column; }
  .field.full-width { grid-column: 1 / -1; }
  .field label {
    font-size: 0.75rem;
    color: var(--text-label);
    margin-bottom: 6px;
    font-weight: 500;
    letter-spacing: 0.3px;
  }
  .field input, .field select {
    background: var(--bg-dark);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 10px 14px;
    border-radius: 8px;
    font-size: 0.9rem;
    font-family: inherit;
    transition: border-color 0.15s;
  }
  .field input:focus, .field select:focus {
    outline: none;
    border-color: var(--accent);
    box-shadow: 0 0 0 3px rgba(56, 189, 248, 0.1);
  }
  .field select {
    -webkit-appearance: none;
    appearance: none;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%2394a3b8' viewBox='0 0 16 16'%3E%3Cpath d='M8 11L3 6h10z'/%3E%3C/svg%3E");
    background-repeat: no-repeat;
    background-position: right 12px center;
    padding-right: 36px;
  }
  .field select option { background: var(--bg-card); color: var(--text); }

  /* ── Range Slider ───────────────────────────────────── */
  .range-row { display: flex; align-items: center; gap: 12px; }
  .range-row input[type=range] {
    flex: 1;
    -webkit-appearance: none;
    background: transparent;
    height: 6px;
  }
  .range-row input[type=range]::-webkit-slider-runnable-track {
    height: 6px;
    background: var(--border);
    border-radius: 3px;
  }
  .range-row input[type=range]::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: var(--accent);
    margin-top: -6px;
    cursor: pointer;
  }
  .range-val {
    font-size: 0.85rem;
    color: var(--accent);
    font-weight: 600;
    min-width: 48px;
    text-align: right;
    font-variant-numeric: tabular-nums;
  }

  /* ── Detection Table ────────────────────────────────── */
  .table-wrap {
    overflow-x: auto;
    max-height: 500px;
    overflow-y: auto;
  }
  table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
  th {
    text-align: left;
    padding: 10px 12px;
    color: var(--text-dim);
    border-bottom: 1px solid var(--border);
    font-weight: 600;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    position: sticky;
    top: 0;
    background: var(--bg-card);
    z-index: 1;
  }
  td {
    padding: 10px 12px;
    border-bottom: 1px solid rgba(30, 45, 69, 0.5);
    font-variant-numeric: tabular-nums;
  }
  tr:hover td { background: rgba(56, 189, 248, 0.03); }
  .confidence-bar {
    width: 60px;
    height: 6px;
    background: var(--border);
    border-radius: 3px;
    overflow: hidden;
    display: inline-block;
    vertical-align: middle;
    margin-right: 6px;
  }
  .confidence-fill {
    height: 100%;
    border-radius: 3px;
    transition: width 0.3s;
  }
  .empty-state {
    text-align: center;
    padding: 40px 20px;
    color: var(--text-dim);
  }
  .empty-state p { margin-top: 8px; font-size: 0.85rem; }

  /* ── Log Viewer ─────────────────────────────────────── */
  .log-controls {
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
  }
  .log-count {
    font-size: 0.75rem;
    color: var(--text-dim);
    margin-left: auto;
  }

  /* ── Toast ──────────────────────────────────────────── */
  .toast {
    position: fixed;
    bottom: 24px;
    right: 24px;
    padding: 14px 24px;
    border-radius: 10px;
    font-weight: 600;
    font-size: 0.85rem;
    display: none;
    z-index: 100;
    box-shadow: 0 8px 24px rgba(0,0,0,0.4);
  }
  .toast.success { background: var(--green); color: #000; }
  .toast.error { background: var(--red); color: #fff; }

  /* ── Responsive ─────────────────────────────────────── */
  @media (max-width: 700px) {
    .grid-2 { grid-template-columns: 1fr; }
    .settings-grid { grid-template-columns: 1fr; }
    .header { flex-direction: column; gap: 8px; }
  }
</style>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>

<div class="header">
  <h1>bark0matic <span class="header-badge">v2</span></h1>
  <div style="display:flex; align-items:center; gap:12px;">
    <div style="display:flex; align-items:center; gap:6px;">
      <span class="pulse-dot" id="header-dot"></span>
      <span id="header-status" style="font-size:0.8rem; color:var(--text-dim);">Connecting...</span>
    </div>
    <button onclick="toggleGuide()" style="background:var(--accent); color:#000; width:32px; height:32px; border-radius:50%; border:none; font-size:1rem; font-weight:700; cursor:pointer; display:flex; align-items:center; justify-content:center;" title="Help &amp; Guide">?</button>
  </div>
</div>

<div class="container">

  <!-- ── Status ────────────────────────────────────────── -->
  <div class="card">
    <div class="card-header">
      <h2>Status</h2>
    </div>
    <div class="status-grid">
      <div class="stat">
        <div class="stat-label">State</div>
        <div class="stat-value" id="state">—</div>
      </div>
      <div class="stat">
        <div class="stat-label">Detecting</div>
        <div class="stat-value" id="sound-type" style="font-size:1.1rem;">—</div>
      </div>
      <div class="stat">
        <div class="stat-label">Detections</div>
        <div class="stat-value" id="count">0</div>
      </div>
      <div class="stat">
        <div class="stat-label">Uptime</div>
        <div class="stat-value" id="uptime" style="font-size:1.1rem;">—</div>
      </div>
      <div class="stat">
        <div class="stat-label">Last Detection</div>
        <div class="stat-value" id="last-detection" style="font-size:0.85rem;">—</div>
      </div>
    </div>
    <div class="controls">
      <button class="btn-start" onclick="control('start')">&#9654; Start</button>
      <button class="btn-stop" onclick="control('stop')">&#9632; Stop</button>
    </div>
  </div>

  <!-- ── Detection History Chart ────────────────────────── -->
  <div class="card">
    <div class="card-header">
      <h2>Detection History</h2>
      <div style="display:flex; gap:4px;">
        <button class="chart-period active" data-period="24h" onclick="setChartPeriod('24h')">24h</button>
        <button class="chart-period" data-period="week" onclick="setChartPeriod('week')">Week</button>
        <button class="chart-period" data-period="month" onclick="setChartPeriod('month')">Month</button>
      </div>
    </div>
    <div style="position:relative; height:220px;">
      <canvas id="historyChart"></canvas>
    </div>
  </div>

  <div class="grid-2">

    <!-- ── Sound Type ──────────────────────────────────── -->
    <div class="card">
      <div class="card-header">
        <h2>Sound Type</h2>
      </div>
      <div class="field">
        <label>What sound to detect</label>
        <select id="sound_type" onchange="soundTypeChanged()"></select>
      </div>
      <p style="font-size:0.75rem; color:var(--text-dim); margin-top:10px;">
        Powered by Google YAMNet — 521 sound classes, runs locally on device.
      </p>
    </div>

    <!-- ── Microphone ────────────────────────────────────── -->
    <div class="card">
      <div class="card-header">
        <h2>Microphone</h2>
      </div>
      <div class="field" style="margin-bottom:14px;">
        <label>Audio Input Device</label>
        <select id="mic_device"></select>
      </div>
      <div class="controls">
        <button style="background:var(--orange); color:#000;" onclick="detectMics()">&#127908; Detect</button>
        <button style="background:var(--blue); color:#000;" onclick="testMic()">&#128266; Test</button>
        <button class="btn-save" onclick="saveMic()">&#128190; Save</button>
      </div>
      <div id="mic-result" style="margin-top:10px; padding:10px; border-radius:8px; font-size:0.85rem; display:none;"></div>
    </div>

    <!-- ── Sensitivity ─────────────────────────────────── -->
    <div class="card">
      <div class="card-header">
        <h2>Sensitivity</h2>
      </div>
      <div class="field" style="margin-bottom:14px;">
        <label>Confidence Threshold</label>
        <div class="range-row">
          <input type="range" id="threshold" min="0.001" max="1" step="0.001"
                 oninput="document.getElementById('threshold-val').textContent=this.value">
          <span class="range-val" id="threshold-val">0.3</span>
        </div>
        <div style="display:flex; justify-content:space-between; font-size:0.65rem; color:var(--text-dim); margin-top:2px;">
          <span>More sensitive</span><span>More accurate</span>
        </div>
      </div>
      <div class="field">
        <label>Energy Threshold (dB)</label>
        <div class="range-row">
          <input type="range" id="energy_threshold" min="-80" max="-10" step="5"
                 oninput="document.getElementById('energy-val').textContent=this.value+'dB'">
          <span class="range-val" id="energy-val">-60dB</span>
        </div>
        <div style="display:flex; justify-content:space-between; font-size:0.65rem; color:var(--text-dim); margin-top:2px;">
          <span>Quieter sounds</span><span>Louder only</span>
        </div>
      </div>
      <div class="field" id="dog-size-field" style="display:none;">
        <label>Large / Small Dog Threshold (Hz)</label>
        <div class="range-row">
          <input type="range" id="dog_size_frequency_threshold" min="500" max="4000" step="100"
                 oninput="updateDogSizeLabel(this.value)">
          <span class="range-val" id="dog-size-val">2000Hz</span>
        </div>
        <div style="display:flex; justify-content:space-between; font-size:0.65rem; color:var(--text-dim); margin-top:2px;">
          <span>&#x1F436; Large dog (&lt; <span id="dog-size-hz">2000</span>Hz)</span>
          <span>Small dog (&gt; <span id="dog-size-hz2">2000</span>Hz) &#x1F436;</span>
        </div>
      </div>
    </div>
  </div>

  <!-- ── Advanced Settings ─────────────────────────────── -->
  <div class="card">
    <div class="card-header">
      <h2>Advanced Settings</h2>
      <button class="btn-clear" onclick="toggleAdvanced()" id="adv-toggle" style="padding:6px 12px; font-size:0.75rem;">Show</button>
    </div>
    <div id="advanced-panel" style="display:none;">
      <div class="settings-grid">
        <div class="field">
          <label>Min Frequency (Hz)</label>
          <input type="number" id="min_frequency" step="50" min="0">
        </div>
        <div class="field">
          <label>Max Frequency (Hz)</label>
          <input type="number" id="max_frequency" step="100" min="0">
        </div>
        <div class="field">
          <label>Chunk Size (seconds)</label>
          <input type="number" id="chunk_size" step="0.5" min="0.5" max="10">
        </div>
        <div class="field">
          <label>Timezone</label>
          <input type="text" id="local_timezone" placeholder="e.g. Australia/Melbourne">
        </div>
        <div class="field">
          <label>Microphone Device</label>
          <input type="text" id="mic_device_adv" disabled style="opacity:0.5;">
        </div>
      </div>
    </div>
    <div style="margin-top:14px; display:flex; gap:10px;">
      <button class="btn-save" onclick="saveSettings()">Save All Settings</button>
      <button class="btn-download" onclick="location.href='/api/download'">&#11015; Download CSV</button>
    </div>
  </div>

  <!-- ── Detections Log ────────────────────────────────── -->
  <div class="card">
    <div class="card-header">
      <h2>Detection Log</h2>
      <div class="log-controls">
        <select id="log-limit" onchange="fetchDetections()" style="background:var(--bg-dark); border:1px solid var(--border); color:var(--text); padding:4px 8px; border-radius:6px; font-size:0.75rem;">
          <option value="25">Last 25</option>
          <option value="50" selected>Last 50</option>
          <option value="100">Last 100</option>
          <option value="500">Last 500</option>
        </select>
        <button class="btn-clear" onclick="clearLog()" style="padding:4px 12px; font-size:0.75rem;">&#128465; Clear Log</button>
        <span class="log-count" id="log-count"></span>
      </div>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Play</th>
            <th>Timestamp</th>
            <th>Sound</th>
            <th>Decibels</th>
            <th>Frequency</th>
            <th>Confidence</th>
            <th>Duration</th>
            <th>Dog Size</th>
          </tr>
        </thead>
        <tbody id="detections"></tbody>
      </table>
      <div class="empty-state" id="empty-state">
        <div style="font-size:2rem; margin-bottom:8px;">&#128266;</div>
        <p>No detections yet. Listening...</p>
      </div>
    </div>
  </div>

</div>

<div class="toast" id="toast"></div>

<!-- ── Guide Overlay ──────────────────────────────────────────── -->
<div id="guide-overlay" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.7); z-index:200; overflow-y:auto; padding:20px;">
<div style="max-width:700px; margin:40px auto; background:var(--bg-card); border:1px solid var(--border); border-radius:16px; padding:32px; position:relative;">
  <button onclick="toggleGuide()" style="position:absolute; top:16px; right:16px; background:none; border:none; color:var(--text-dim); font-size:1.5rem; cursor:pointer;">&times;</button>

  <h2 style="font-size:1.4rem; color:var(--accent); margin-bottom:24px;">How to Use bark0matic</h2>

  <div class="guide-section">
    <h3>What is bark0matic?</h3>
    <p>bark0matic uses AI to listen for specific sounds through a microphone connected to your Raspberry Pi. When it detects the target sound (e.g. a dog barking), it logs the event with a timestamp, volume level, and confidence score. This data can be exported as a CSV file for use as evidence in noise complaints or other purposes.</p>
  </div>

  <div class="guide-section">
    <h3>How Detection Works</h3>
    <p>bark0matic uses <strong>YAMNet</strong>, a Google AI model trained on over 2 million audio clips covering 521 different sounds. It runs entirely on your Raspberry Pi — no internet required after setup.</p>
    <p>Every 2 seconds, the microphone captures audio. YAMNet analyses it and returns a <strong>confidence score</strong> (0 to 1) for each sound type. If the score exceeds your threshold, it's logged as a detection.</p>
    <ul>
      <li><strong>0.8 - 1.0</strong> — Very confident. Almost certainly the target sound.</li>
      <li><strong>0.5 - 0.8</strong> — Likely the target sound, some uncertainty.</li>
      <li><strong>0.2 - 0.5</strong> — Possible detection. May include similar sounds.</li>
      <li><strong>Below 0.2</strong> — Probably not the target sound.</li>
    </ul>
  </div>

  <div class="guide-section">
    <h3>Understanding Settings</h3>
    <table style="width:100%; font-size:0.85rem;">
      <tr><td style="padding:8px; color:var(--accent); white-space:nowrap; vertical-align:top; font-weight:600;">Confidence Threshold</td>
          <td style="padding:8px;">The minimum confidence score required to log a detection. Lower = more sensitive (catches more but may have false positives). Higher = more accurate (fewer detections but more reliable). <strong>Start at 0.3</strong> and adjust based on results.</td></tr>
      <tr><td style="padding:8px; color:var(--accent); white-space:nowrap; vertical-align:top; font-weight:600;">Energy Threshold</td>
          <td style="padding:8px;">Minimum volume (in decibels) to trigger detection. Set lower for distant sounds, higher to ignore quiet background noise. <strong>-60dB</strong> catches distant sounds; <strong>-30dB</strong> only catches loud nearby sounds.</td></tr>
      <tr><td style="padding:8px; color:var(--accent); white-space:nowrap; vertical-align:top; font-weight:600;">Min/Max Frequency</td>
          <td style="padding:8px;">Frequency range filter (in Hz). Useful for filtering by pitch — e.g. large dogs bark at lower frequencies (80-500Hz) than small dogs (500-2000Hz). Leave at 50-5000Hz to capture everything.</td></tr>
      <tr><td style="padding:8px; color:var(--accent); white-space:nowrap; vertical-align:top; font-weight:600;">Chunk Size</td>
          <td style="padding:8px;">How many seconds of audio to analyse at once. 2 seconds is the default. Longer chunks may improve accuracy but add delay.</td></tr>
      <tr><td style="padding:8px; color:var(--accent); white-space:nowrap; vertical-align:top; font-weight:600;">Sound Type</td>
          <td style="padding:8px;">What sound to listen for. Change this to detect different sounds — dog bark, cat meow, siren, glass breaking, etc. The AI model supports 18 categories.</td></tr>
    </table>
  </div>

  <div class="guide-section">
    <h3>Reading the Detection Log</h3>
    <table style="width:100%; font-size:0.85rem;">
      <tr><td style="padding:6px; color:var(--accent); font-weight:600;">Timestamp</td><td style="padding:6px;">When the sound was detected, in your local timezone.</td></tr>
      <tr><td style="padding:6px; color:var(--accent); font-weight:600;">Sound</td><td style="padding:6px;">The type of sound detected (e.g. "Dog bark").</td></tr>
      <tr><td style="padding:6px; color:var(--accent); font-weight:600;">Decibels</td><td style="padding:6px;">Volume level. Typical values: -20dB (loud), -40dB (moderate), -60dB (quiet).</td></tr>
      <tr><td style="padding:6px; color:var(--accent); font-weight:600;">Frequency</td><td style="padding:6px;">The dominant pitch of the sound in Hz.</td></tr>
      <tr><td style="padding:6px; color:var(--accent); font-weight:600;">Confidence</td><td style="padding:6px;">How sure the AI is (0-1). Green bar = high confidence.</td></tr>
      <tr><td style="padding:6px; color:var(--accent); font-weight:600;">Duration</td><td style="padding:6px;">Length of the audio chunk analysed (usually 2 seconds).</td></tr>
    </table>
  </div>

  <div class="guide-section">
    <h3>Tips for Best Results</h3>
    <ul>
      <li><strong>Microphone placement:</strong> Point the mic toward the sound source. Place it near a window if monitoring outdoor noise.</li>
      <li><strong>Distance:</strong> The further the sound source, the lower the confidence and decibel readings. Reduce the energy threshold for distant sounds.</li>
      <li><strong>False positives:</strong> If you're getting too many false detections, increase the confidence threshold (e.g. from 0.3 to 0.5).</li>
      <li><strong>Missing detections:</strong> If real sounds aren't being caught, decrease the confidence threshold and/or the energy threshold.</li>
      <li><strong>Large vs small dogs:</strong> Set frequency range to 80-800Hz to focus on large deep-barking dogs. Set 500-2000Hz for small dogs.</li>
      <li><strong>Background noise:</strong> If the mic picks up too much ambient noise, increase the energy threshold to require louder sounds.</li>
    </ul>
  </div>

  <div class="guide-section">
    <h3>Exporting Evidence</h3>
    <p>Click <strong>Download CSV</strong> to export all logged detections as a spreadsheet file. This file contains:</p>
    <ul>
      <li>Exact date and time of every detection</li>
      <li>Volume level (decibels) — shows how loud the sound was</li>
      <li>Confidence score — shows how certain the AI identification was</li>
      <li>Frequency data — can help distinguish sound types</li>
    </ul>
    <p>This CSV can be opened in Excel, Google Sheets, or any spreadsheet program. When submitting a noise complaint to your local council, include:</p>
    <ol>
      <li>The CSV file as evidence</li>
      <li>A summary: "Between [dates], [X] instances of [sound] were detected"</li>
      <li>Note the times — especially overnight or early morning detections</li>
      <li>Highlight the worst offenders (highest decibel readings)</li>
    </ol>
  </div>

  <div style="text-align:center; margin-top:20px; padding-top:16px; border-top:1px solid var(--border);">
    <button onclick="toggleGuide()" class="btn-save" style="padding:10px 30px;">Got it</button>
  </div>
</div>
</div>

<style>
  .guide-section { margin-bottom: 24px; }
  .guide-section h3 { font-size: 1rem; color: var(--green); margin-bottom: 10px; font-weight: 600; }
  .guide-section p { font-size: 0.9rem; color: var(--text); line-height: 1.6; margin-bottom: 8px; }
  .guide-section ul, .guide-section ol { font-size: 0.9rem; color: var(--text); line-height: 1.6; padding-left: 20px; margin-bottom: 8px; }
  .guide-section li { margin-bottom: 6px; }
  .guide-section strong { color: var(--accent); }
</style>

<script>
let soundCategories = [];

let currentAudio = null;
let currentBtn = null;
function playAudio(filename, btn) {
  if (currentAudio) {
    currentAudio.pause();
    currentAudio = null;
    if (currentBtn) { currentBtn.textContent = '▶'; currentBtn.style.color = ''; }
  }
  btn.textContent = '⏳';
  const audio = new Audio('/api/audio/' + encodeURIComponent(filename));
  audio.oncanplay = () => { btn.textContent = '🔊'; btn.style.color = 'var(--orange)'; };
  audio.onended = () => { btn.textContent = '▶'; btn.style.color = ''; currentAudio = null; currentBtn = null; };
  audio.onerror = () => { btn.textContent = '❌'; btn.style.color = 'red'; setTimeout(() => { btn.textContent = '▶'; btn.style.color = ''; }, 2000); };
  audio.play().catch(e => { btn.textContent = '❌'; btn.style.color = 'red'; setTimeout(() => { btn.textContent = '▶'; btn.style.color = ''; }, 2000); console.error('Playback failed:', e); });
  currentAudio = audio;
  currentBtn = btn;
}

function confColor(c) {
  const v = parseFloat(c) || 0;
  if (v >= 0.7) return 'var(--green)';
  if (v >= 0.4) return 'var(--orange)';
  return 'var(--red)';
}

async function fetchStatus() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    const el = document.getElementById('state');
    el.textContent = d.running ? 'Listening' : 'Stopped';
    el.className = 'stat-value ' + (d.running ? 'running' : 'stopped');
    document.getElementById('sound-type').textContent = d.sound_type || '—';
    document.getElementById('count').textContent = d.total_logged || 0;
    document.getElementById('uptime').textContent = d.uptime || '—';
    document.getElementById('header-status').textContent = d.running ? 'Listening for ' + d.sound_type : 'Stopped';
    document.getElementById('header-status').style.color = d.running ? 'var(--green)' : 'var(--red)';
    const dot = document.getElementById('header-dot');
    dot.className = 'pulse-dot ' + (d.running ? 'running' : 'stopped');

    if (d.last_detection) {
      const ld = d.last_detection;
      document.getElementById('last-detection').textContent =
        ld.timestamp + ' (' + ld.decibels + 'dB)';
    }
  } catch(e) {
    document.getElementById('header-status').textContent = 'Connection error';
    document.getElementById('header-status').style.color = 'var(--red)';
  }
}

async function fetchDetections() {
  try {
    const limit = document.getElementById('log-limit').value;
    const r = await fetch('/api/detections?count=' + limit);
    const rows = await r.json();
    const tbody = document.getElementById('detections');
    const empty = document.getElementById('empty-state');

    if (rows.length === 0) {
      tbody.innerHTML = '';
      empty.style.display = 'block';
      document.getElementById('log-count').textContent = '';
      return;
    }
    empty.style.display = 'none';
    document.getElementById('log-count').textContent = rows.length + ' events';

    tbody.innerHTML = rows.map(r => {
      const conf = parseFloat(r.confidence) || 0;
      const pct = Math.min(conf * 100, 100);
      const playBtn = r.audio_file
        ? `<button onclick="playAudio('${r.audio_file}', this)" style="background:none; border:none; cursor:pointer; font-size:1.1rem; padding:2px 6px;" title="Play recording">▶</button>`
        : '<span style="color:var(--text-dim); font-size:0.7rem;">—</span>';
      return `<tr>
        <td>${playBtn}</td>
        <td style="white-space:nowrap;">${r.timestamp || ''}</td>
        <td>${r.sound_type || ''}</td>
        <td>${r.decibels || ''}dB</td>
        <td>${r.frequency_hz || ''}Hz</td>
        <td>
          <span class="confidence-bar"><span class="confidence-fill" style="width:${pct}%; background:${confColor(r.confidence)};"></span></span>
          ${r.confidence || ''}
        </td>
        <td>${r.duration_seconds || ''}s</td>
        <td>${r.dog_size || ''}</td>
      </tr>`;
    }).join('');
  } catch(e) { console.error(e); }
}

async function loadSettings() {
  try {
    const r = await fetch('/api/settings');
    const d = await r.json();

    // Threshold slider
    document.getElementById('threshold').value = d.threshold;
    document.getElementById('threshold-val').textContent = d.threshold;

    // Energy slider
    document.getElementById('energy_threshold').value = d.energy_threshold;
    document.getElementById('energy-val').textContent = d.energy_threshold + 'dB';

    // Dog size slider (only relevant for dog bark)
    const dsVal = d.dog_size_frequency_threshold || 2000;
    document.getElementById('dog_size_frequency_threshold').value = dsVal;
    updateDogSizeLabel(dsVal);
    toggleDogSizeField(d.sound_type_name);

    // Advanced fields
    document.getElementById('min_frequency').value = d.min_frequency;
    document.getElementById('max_frequency').value = d.max_frequency;
    document.getElementById('chunk_size').value = d.chunk_size;
    document.getElementById('local_timezone').value = d.local_timezone || '';
    document.getElementById('mic_device_adv').value = d.microphone_device;

    // Sound type dropdown
    soundCategories = d.sound_categories || [];
    const sel = document.getElementById('sound_type');
    sel.innerHTML = soundCategories.map(c =>
      `<option value="${c.name}" ${c.name === d.sound_type_name ? 'selected' : ''}>${c.name}</option>`
    ).join('');
  } catch(e) { console.error(e); }
}

function updateDogSizeLabel(hz) {
  document.getElementById('dog-size-val').textContent = hz + 'Hz';
  document.getElementById('dog-size-hz').textContent = hz;
  document.getElementById('dog-size-hz2').textContent = hz;
}

function toggleDogSizeField(soundTypeName) {
  const isDog = (soundTypeName || '').toLowerCase().includes('dog');
  document.getElementById('dog-size-field').style.display = isDog ? '' : 'none';
}

function soundTypeChanged() {
  const name = document.getElementById('sound_type').value;
  document.getElementById('sound-type').textContent = name;
  toggleDogSizeField(name);
}

async function saveSettings() {
  const data = {
    threshold: parseFloat(document.getElementById('threshold').value),
    energy_threshold: parseFloat(document.getElementById('energy_threshold').value),
    min_frequency: parseFloat(document.getElementById('min_frequency').value),
    max_frequency: parseFloat(document.getElementById('max_frequency').value),
    chunk_size: parseFloat(document.getElementById('chunk_size').value),
    local_timezone: document.getElementById('local_timezone').value.trim(),
    sound_type_name: document.getElementById('sound_type').value,
    dog_size_frequency_threshold: parseInt(document.getElementById('dog_size_frequency_threshold').value),
  };
  try {
    await fetch('/api/settings', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data)
    });
    showToast('Settings saved — detector reloaded', 'success');
  } catch(e) {
    showToast('Failed to save settings', 'error');
  }
}

async function control(action) {
  try {
    await fetch('/api/control', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({action})
    });
    showToast(action === 'start' ? 'Detector started' : 'Detector stopped', 'success');
    setTimeout(fetchStatus, 500);
  } catch(e) {
    showToast('Failed to ' + action, 'error');
  }
}

function toggleAdvanced() {
  const p = document.getElementById('advanced-panel');
  const b = document.getElementById('adv-toggle');
  if (p.style.display === 'none') {
    p.style.display = 'block';
    b.textContent = 'Hide';
  } else {
    p.style.display = 'none';
    b.textContent = 'Show';
  }
}

function showToast(msg, type) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast ' + type;
  t.style.display = 'block';
  setTimeout(() => t.style.display = 'none', 2500);
}

async function clearLog() {
  if (!confirm('Clear all logged detections? This cannot be undone.')) return;
  try {
    await fetch('/api/clear-log', {method: 'POST'});
    showToast('Log cleared', 'success');
    fetchDetections();
    fetchStatus();
  } catch(e) {
    showToast('Failed to clear log', 'error');
  }
}

function toggleGuide() {
  const g = document.getElementById('guide-overlay');
  g.style.display = g.style.display === 'none' ? 'block' : 'none';
}

async function detectMics(silent) {
  const r = document.getElementById('mic-result');
  const sel = document.getElementById('mic_device');
  if (!silent) {
    r.style.display = 'block';
    r.style.background = 'var(--bg-dark)';
    r.style.color = 'var(--text-dim)';
    r.textContent = 'Detecting microphones...';
  }

  try {
    const res = await fetch('/api/detect-microphone');
    const data = await res.json();

    if (data.status === 'ok') {
      sel.innerHTML = '';

      // If no devices found via arecord, show current config as option
      if (data.devices.length === 0 && data.current) {
        const opt = document.createElement('option');
        opt.value = data.current;
        opt.textContent = data.current + ' (configured)';
        sel.appendChild(opt);
      }

      data.devices.forEach(d => {
        const opt = document.createElement('option');
        opt.value = d.id;
        opt.textContent = d.label;
        if (d.id === data.current) opt.selected = true;
        sel.appendChild(opt);
      });

      // If nothing matched current, select first USB device
      if (!sel.value && data.devices.length > 0) {
        sel.selectedIndex = 0;
      }

      if (!silent) {
        r.style.display = 'block';
        r.style.background = 'var(--green-bg)';
        r.style.color = 'var(--green)';
        r.textContent = data.devices.length + ' microphone(s) found';
      }
    } else if (!silent) {
      r.style.background = 'var(--red-bg)';
      r.style.color = 'var(--red)';
      r.textContent = 'No microphones detected';
    }
  } catch (e) {
    if (!silent) {
      r.style.background = 'var(--red-bg)';
      r.style.color = 'var(--red)';
      r.textContent = 'Detection failed: ' + e.message;
    }
  }
}

async function testMic() {
  const r = document.getElementById('mic-result');
  const device = document.getElementById('mic_device').value;
  r.style.display = 'block';
  r.style.background = 'var(--bg-dark)';
  r.style.color = 'var(--text-dim)';
  r.textContent = 'Recording 2 seconds...';

  try {
    const res = await fetch('/api/test-microphone?device=' + encodeURIComponent(device));
    const data = await res.json();

    if (data.status === 'ok') {
      r.style.background = 'var(--green-bg)';
      r.style.color = 'var(--green)';
      r.textContent = `✓ Working! ${data.db}dB, Peak: ${data.peak}%`;
    } else {
      r.style.background = data.status === 'warning' ? 'rgba(251,146,60,0.1)' : 'var(--red-bg)';
      r.style.color = data.status === 'warning' ? 'var(--orange)' : 'var(--red)';
      r.textContent = data.message;
    }
  } catch (e) {
    r.style.background = 'var(--red-bg)';
    r.style.color = 'var(--red)';
    r.textContent = 'Test failed: ' + e.message;
  }
}

async function saveMic() {
  const device = document.getElementById('mic_device').value;
  const r = document.getElementById('mic-result');

  try {
    const res = await fetch('/api/save-microphone', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({device})
    });
    const data = await res.json();

    r.style.display = 'block';
    if (data.status === 'ok') {
      r.style.background = 'var(--green-bg)';
      r.style.color = 'var(--green)';
      r.textContent = '✓ Saved! Using: ' + device;
      showToast('Microphone saved: ' + device, 'success');
    } else {
      r.style.background = 'var(--red-bg)';
      r.style.color = 'var(--red)';
      r.textContent = 'Save failed: ' + data.message;
    }
  } catch (e) {
    r.style.background = 'var(--red-bg)';
    r.style.color = 'var(--red)';
    r.textContent = 'Save failed: ' + e.message;
  }
}

// ── Init ──────────────────────────────────────────────
// ── Detection History Chart ──────────────────────────
let historyChart = null;
let chartPeriod = '24h';

function setChartPeriod(p) {
  chartPeriod = p;
  document.querySelectorAll('.chart-period').forEach(b => b.classList.toggle('active', b.dataset.period === p));
  fetchChartData();
}

async function fetchChartData() {
  try {
    const r = await fetch('/api/chart-data?period=' + chartPeriod);
    const d = await r.json();
    if (d.error) return;

    const ctx = document.getElementById('historyChart').getContext('2d');
    if (historyChart) {
      historyChart.data.labels = d.labels;
      historyChart.data.datasets[0].data = d.counts;
      historyChart.data.datasets[0].backgroundColor = d.counts.map(c => c > 0 ? '#f97316' : 'rgba(255,255,255,0.05)');
      historyChart.update();
    } else {
      historyChart = new Chart(ctx, {
        type: 'bar',
        data: {
          labels: d.labels,
          datasets: [{
            label: 'Detections',
            data: d.counts,
            backgroundColor: d.counts.map(c => c > 0 ? '#f97316' : 'rgba(255,255,255,0.05)'),
            borderRadius: 4,
            borderSkipped: false,
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                title: (items) => items[0].label,
                label: (item) => item.raw + ' detection' + (item.raw !== 1 ? 's' : '')
              }
            }
          },
          scales: {
            x: {
              ticks: { color: '#9ca3af', font: { size: 10 }, maxRotation: 45 },
              grid: { display: false }
            },
            y: {
              beginAtZero: true,
              ticks: { color: '#9ca3af', stepSize: 1, precision: 0 },
              grid: { color: 'rgba(255,255,255,0.06)' }
            }
          }
        }
      });
    }
  } catch(e) { console.error('Chart error:', e); }
}

loadSettings();
fetchStatus();
fetchDetections();
fetchChartData();
detectMics(true);
setInterval(fetchStatus, 3000);
setInterval(fetchDetections, 5000);
setInterval(fetchChartData, 30000);
</script>
</body>
</html>"""
