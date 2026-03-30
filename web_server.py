"""Flask web interface for bark0matic."""
import io
import os
import secrets
import subprocess
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, jsonify, request, send_file, render_template_string, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config
from incident_model import IncidentManager
import report_exporter

# Will be set by main.py
detector = None

# Fallback categories when the full YAMNet class map is unavailable.
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
    {"name": "Music", "indices": [132, 249]},
]


def get_app_version():
    """Read the current app version from VERSION."""
    version_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION")
    try:
        with open(version_path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except Exception:
        return "unknown"


APP_VERSION = get_app_version()


def create_app(sound_detector):
    """Create Flask app with reference to the detector."""
    global detector
    detector = sound_detector

    # Ensure a persistent secret key exists for Flask sessions
    if not Config.FLASK_SECRET_KEY:
        Config.FLASK_SECRET_KEY = secrets.token_hex(32)
        Config.save()

    app = Flask(__name__)
    app.secret_key = Config.FLASK_SECRET_KEY
    incident_mgr = IncidentManager(Config.LOG_DB_PATH)

    # ------------------------------------------------------------------
    # Officer portal auth helpers
    # ------------------------------------------------------------------

    def _check_officer_password(username: str, password: str) -> bool:
        if username != Config.OFFICER_USERNAME:
            return False
        if Config.OFFICER_PASSWORD_HASH:
            return check_password_hash(Config.OFFICER_PASSWORD_HASH, password)
        # Default password "sentinel" if no hash configured
        return password == "sentinel"

    def require_officer(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not session.get("officer_logged_in"):
                return redirect(url_for("portal_login", next=request.path))
            return f(*args, **kwargs)
        return decorated

    @app.route("/")
    def dashboard():
        return render_template_string(DASHBOARD_HTML, app_version=APP_VERSION)

    @app.route("/changelog")
    def changelog():
        changelog_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "CHANGELOG.md")
        return send_file(changelog_path, mimetype="text/markdown")

    @app.route("/api/status")
    def api_status():
        status = detector.get_status()
        status["version"] = APP_VERSION
        return jsonify(status)

    @app.route("/api/detections")
    def api_detections():
        count = request.args.get("count", 100, type=int)
        search = request.args.get("search", "", type=str)
        audio_only = request.args.get("audio_only", "0") in ("1", "true", "yes", "on")
        rows = detector.logger.get_recent(count, search=search, audio_only=audio_only)
        return jsonify(rows)

    @app.route("/api/settings", methods=["GET"])
    def api_get_settings():
        data = Config.to_dict()
        available_sounds = detector.classifier.get_available_sounds() if detector else []
        data["available_sounds"] = available_sounds or [
            {"name": item["name"], "index": item["indices"][0]}
            for item in SOUND_CATEGORIES
        ]
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
        if "quiet_hours_enabled" in data:
            Config.QUIET_HOURS_ENABLED = bool(data["quiet_hours_enabled"])
        if "quiet_hours_weekday" in data:
            qw = data["quiet_hours_weekday"]
            if isinstance(qw, dict) and "start" in qw and "end" in qw:
                Config.QUIET_HOURS_WEEKDAY = {"start": str(qw["start"]), "end": str(qw["end"])}
        if "quiet_hours_weekend" in data:
            qe = data["quiet_hours_weekend"]
            if isinstance(qe, dict) and "start" in qe and "end" in qe:
                Config.QUIET_HOURS_WEEKEND = {"start": str(qe["start"]), "end": str(qe["end"])}
        Config.SOUND_TYPE_NAME = "All sounds"
        Config.SOUND_TYPE_INDICES = []
        if "record_sound_indices" in data:
            indices = []
            for value in data["record_sound_indices"]:
                try:
                    index = int(value)
                except (TypeError, ValueError):
                    continue
                if index not in indices:
                    indices.append(index)
                if len(indices) == 10:
                    break
            Config.RECORD_SOUND_INDICES = indices

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

    @app.route("/api/free-disk-space", methods=["POST"])
    def api_free_disk_space():
        try:
            result = detector.cleanup_old_recordings(days=30)
            return jsonify({"status": "ok", **result})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route("/api/download")
    def api_download():
        search = request.args.get("search", "", type=str)
        audio_only = request.args.get("audio_only", "0") in ("1", "true", "yes", "on")
        csv_path = detector.logger.get_csv_path(search=search, audio_only=audio_only)
        return send_file(csv_path, as_attachment=True, download_name="detections.csv")

    @app.route("/api/incidents")
    def api_incidents():
        """Return grouped incidents (processes any pending detections first)."""
        incident_mgr.process_new_detections()
        count = request.args.get("count", 50, type=int)
        event_type = request.args.get("event_type", None, type=str)
        review_status = request.args.get("review_status", None, type=str)
        rows = incident_mgr.get_recent_incidents(
            count=count,
            event_type=event_type,
            review_status=review_status,
        )
        return jsonify(rows)

    @app.route("/api/incidents/<incident_id>", methods=["GET"])
    def api_get_incident(incident_id):
        incident = incident_mgr.get_incident(incident_id)
        if incident is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(incident)

    @app.route("/api/incidents/<incident_id>", methods=["PATCH"])
    def api_update_incident(incident_id):
        data = request.json or {}
        ok = incident_mgr.update_incident(
            incident_id,
            review_status=data.get("review_status"),
            tenant_marked=data.get("tenant_marked"),
            case_id=data.get("case_id"),
        )
        if not ok:
            return jsonify({"error": "update failed or invalid fields"}), 400
        return jsonify({"status": "ok"})

    @app.route("/api/export/incidents.csv")
    def api_export_incidents_csv():
        """Export incidents as a CSV complaint diary."""
        incident_mgr.process_new_detections()
        count = request.args.get("count", 1000, type=int)
        event_type = request.args.get("event_type", None, type=str)
        review_status = request.args.get("review_status", None, type=str)
        date_from = request.args.get("date_from", None, type=str)
        date_to = request.args.get("date_to", None, type=str)
        rows = incident_mgr.get_recent_incidents(
            count=count,
            event_type=event_type,
            review_status=review_status,
            date_from=date_from,
            date_to=date_to,
        )
        csv_bytes = report_exporter.export_csv(rows)
        return send_file(
            io.BytesIO(csv_bytes),
            mimetype="text/csv",
            as_attachment=True,
            download_name="sentinel_complaint_diary.csv",
        )

    @app.route("/api/export/incidents.pdf")
    def api_export_incidents_pdf():
        """Export incidents as a PDF complaint diary report."""
        incident_mgr.process_new_detections()
        count = request.args.get("count", 1000, type=int)
        event_type = request.args.get("event_type", None, type=str)
        review_status = request.args.get("review_status", None, type=str)
        date_from = request.args.get("date_from", None, type=str)
        date_to = request.args.get("date_to", None, type=str)
        rows = incident_mgr.get_recent_incidents(
            count=count,
            event_type=event_type,
            review_status=review_status,
            date_from=date_from,
            date_to=date_to,
        )
        try:
            pdf_bytes = report_exporter.export_pdf(
                rows,
                property_address=Config.PROPERTY_ADDRESS,
                device_id=Config.RPI_MICROPHONE_DEVICE,
            )
        except ImportError:
            return jsonify({"error": "reportlab is not installed. Run: pip install reportlab"}), 500
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name="sentinel_complaint_diary.pdf",
        )

    @app.route("/api/update", methods=["POST"])
    def api_update():
        """Start a background software update from GitHub and restart the service."""
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            log_path = "/tmp/barkomatic_update.log"

            subprocess.Popen(
                [
                    "bash",
                    "-lc",
                    f"cd {script_dir!r} && nohup bash update.sh > {log_path!r} 2>&1 &",
                ],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            return jsonify({
                "status": "started",
                "message": "Update started. The dashboard will reconnect after the service restarts.",
                "log_path": log_path,
            })
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route("/api/audio/<filename>")
    def api_audio(filename):
        """Serve a recorded audio clip for playback."""
        audio_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recordings")
        filepath = os.path.join(audio_dir, filename)
        if not os.path.exists(filepath):
            return jsonify({"error": "not found"}), 404
        return send_file(filepath, mimetype="audio/wav")

    @app.route("/api/snapshot/<filename>")
    def api_snapshot(filename):
        """Serve a saved image captured alongside a recording."""
        filepath = detector.get_snapshot_path(filename)
        if not os.path.exists(filepath):
            return jsonify({"error": "not found"}), 404
        return send_file(filepath, mimetype="image/jpeg")

    @app.route("/api/camera/live")
    def api_camera_live():
        """Capture and serve a live snapshot from the connected Pi camera."""
        filepath = detector.capture_live_snapshot()
        if not filepath or not os.path.exists(filepath):
            return jsonify({"error": "camera unavailable"}), 503
        return send_file(filepath, mimetype="image/jpeg")

    @app.route("/api/detect-microphone")
    def api_detect_microphone():
        """Detect available audio input devices."""
        try:
            import subprocess
            import re

            devices = []

            # Detect via arecord (Linux) - gives card numbers
            try:
                result = subprocess.run(['arecord', '-l'], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        m = re.match(r'card (\d+):.*\[(.+?)\].*device (\d+):', line)
                        if m:
                            card, name, dev = m.group(1), m.group(2).strip(), m.group(3)
                            name_lower = name.lower()

                            # For HAT devices, use ALSA default capture device
                            # The seeed-voicecard driver configures /etc/asound.conf
                            # with a dsnoop plugin routed through 'default' and 'capture'
                            if 'seeed' in name_lower or 'wm8960' in name_lower:
                                device_id = 'default'
                                label = f"seeed-2mic-voicecard (HAT)"
                            else:
                                device_id = f"hw:{card},{dev}"
                                label = f"hw:{card},{dev} - {name}"

                            devices.append({
                                "id": device_id,
                                "name": name,
                                "label": label
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
        """Test microphone by recording 2 seconds of audio via arecord."""
        device = request.args.get("device", Config.RPI_MICROPHONE_DEVICE)
        try:
            import subprocess
            import wave
            import numpy as np
            import time
            import tempfile
            import os

            SAMPLE_RATE = Config.RPI_MICROPHONE_RATE
            DURATION = 2

            # Stop detector to free the mic
            was_running = detector.running
            if was_running:
                detector.stop()
                time.sleep(1)

            print(f"[MIC] Testing device: {device}")
            raw_device = device if device and device != "auto" else "hw:2,0"
            # For HAT devices like seeed-2mic-voicecard, use the ALSA plugin device
            # which handles format/rate/channel conversion properly
            alsa_device = raw_device.replace("hw:", "plughw:", 1) if raw_device.startswith("hw:") else raw_device

            tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
            tmp_path = tmp.name
            tmp.close()

            try:
                cmd = [
                    'arecord', '-D', alsa_device,
                    '-f', 'S16_LE', '-r', str(SAMPLE_RATE),
                    '-c', '1', '-d', str(DURATION),
                    '-t', 'wav', '-q', tmp_path
                ]
                result = subprocess.run(cmd, capture_output=True, timeout=DURATION + 5)

                if result.returncode != 0:
                    raise RuntimeError(f"arecord failed: {result.stderr.decode().strip()}")

                with wave.open(tmp_path, 'rb') as wf:
                    frames = wf.readframes(wf.getnframes())
                    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
                    # Convert stereo to mono if needed
                    if wf.getnchannels() == 2:
                        audio = audio.reshape(-1, 2).mean(axis=1)
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
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

    # ------------------------------------------------------------------
    # Officer portal
    # ------------------------------------------------------------------

    @app.route("/portal/login", methods=["GET", "POST"])
    def portal_login():
        error = None
        if request.method == "POST":
            username = request.form.get("username", "")
            password = request.form.get("password", "")
            if _check_officer_password(username, password):
                session["officer_logged_in"] = True
                next_url = request.args.get("next") or url_for("portal_cases")
                return redirect(next_url)
            error = "Invalid username or password."
        return render_template_string(PORTAL_LOGIN_HTML, error=error)

    @app.route("/portal/logout", methods=["POST"])
    def portal_logout():
        session.pop("officer_logged_in", None)
        return redirect(url_for("portal_login"))

    @app.route("/portal")
    @require_officer
    def portal_cases():
        incident_mgr.process_new_detections()
        cases = incident_mgr.get_cases()
        return render_template_string(
            PORTAL_CASES_HTML,
            cases=cases,
            property_address=Config.PROPERTY_ADDRESS or "Unknown property",
        )

    @app.route("/portal/case/<case_id>")
    @require_officer
    def portal_case_detail(case_id):
        incident_mgr.process_new_detections()
        actual_case_id = None if case_id == "unassigned" else case_id
        incidents = incident_mgr.get_case_incidents(actual_case_id)

        # Aggregate stats
        total = len(incidents)
        qh_violations = sum(1 for i in incidents if i.get("quiet_hours_violation"))
        qh_pct = round(qh_violations / total * 100) if total else 0
        by_type: dict = {}
        for inc in incidents:
            et = inc.get("event_type", "unknown")
            by_type[et] = by_type.get(et, 0) + 1

        # Hour-of-day heatmap data (0-23)
        hour_counts = [0] * 24
        dow_counts = [0] * 7  # Monday=0
        for inc in incidents:
            ts = inc.get("started_at", "")
            try:
                dt = datetime.fromisoformat(ts)
                hour_counts[dt.hour] += 1
                dow_counts[dt.weekday()] += 1
            except Exception:
                pass

        return render_template_string(
            PORTAL_CASE_HTML,
            case_id=case_id,
            actual_case_id=actual_case_id,
            incidents=incidents,
            total=total,
            qh_violations=qh_violations,
            qh_pct=qh_pct,
            by_type=by_type,
            hour_counts=hour_counts,
            dow_counts=dow_counts,
            property_address=Config.PROPERTY_ADDRESS or "Unknown property",
        )

    @app.route("/portal/case/<case_id>/report.pdf")
    @require_officer
    def portal_case_report_pdf(case_id):
        incident_mgr.process_new_detections()
        actual_case_id = None if case_id == "unassigned" else case_id
        incidents = incident_mgr.get_case_incidents(actual_case_id)
        try:
            pdf_bytes = report_exporter.export_pdf(
                incidents,
                property_address=Config.PROPERTY_ADDRESS,
                device_id=Config.RPI_MICROPHONE_DEVICE,
            )
        except ImportError:
            return "reportlab is not installed. Run: pip install reportlab", 500
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"sentinel_case_{case_id}.pdf",
        )

    @app.route("/portal/settings", methods=["GET", "POST"])
    @require_officer
    def portal_settings():
        message = None
        if request.method == "POST":
            new_username = request.form.get("username", "").strip()
            new_password = request.form.get("password", "").strip()
            if new_username:
                Config.OFFICER_USERNAME = new_username
            if new_password:
                Config.OFFICER_PASSWORD_HASH = generate_password_hash(new_password)
            Config.save()
            message = "Settings saved."
        return render_template_string(
            PORTAL_SETTINGS_HTML,
            username=Config.OFFICER_USERNAME,
            message=message,
        )

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
  .meter-wrap {
    margin-top: 8px;
  }
  .meter-bar {
    width: 100%;
    height: 10px;
    border-radius: 999px;
    background: rgba(255,255,255,0.06);
    overflow: hidden;
    border: 1px solid var(--border);
  }
  .meter-fill {
    height: 100%;
    width: 0%;
    background: linear-gradient(90deg, var(--green), var(--orange), var(--red));
    transition: width 0.2s ease;
  }
  .meter-meta {
    margin-top: 6px;
    font-size: 0.75rem;
    color: var(--text-dim);
    display: flex;
    justify-content: space-between;
    gap: 8px;
  }

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
  .btn-update { background: var(--orange); color: #000; }
  .btn-clear { background: transparent; border: 1px solid var(--border); color: var(--text-dim); }
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
  .pill-list {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 10px;
  }
  .field-hint {
    font-size: 0.9rem;
    color: var(--accent);
    margin-top: 8px;
    line-height: 1.5;
    font-weight: 700;
    padding: 10px 12px;
    border-radius: 8px;
    border: 1px solid rgba(56, 189, 248, 0.28);
    background: rgba(56, 189, 248, 0.08);
  }
  .field-warning {
    margin-top: 10px;
    padding: 10px 12px;
    border-radius: 8px;
    border: 1px solid rgba(248, 113, 113, 0.28);
    background: rgba(248, 113, 113, 0.1);
    color: var(--red);
    font-size: 0.82rem;
    line-height: 1.45;
    display: none;
  }
  .field-subsection {
    margin-top: 18px;
    padding-top: 16px;
    border-top: 1px solid var(--border);
  }
  .pill {
    display: inline-flex;
    align-items: center;
    padding: 6px 10px;
    border-radius: 999px;
    background: rgba(56, 189, 248, 0.12);
    border: 1px solid rgba(56, 189, 248, 0.28);
    color: var(--accent);
    font-size: 0.75rem;
    font-weight: 600;
    line-height: 1;
  }
  .pill-button {
    cursor: pointer;
    font-family: inherit;
    background: rgba(56, 189, 248, 0.12);
    color: var(--accent);
    border: 1px solid rgba(56, 189, 248, 0.28);
    box-shadow: none;
    transform: none;
    gap: 8px;
    padding: 6px 10px;
  }
  .pill-button:hover {
    transform: none;
    filter: brightness(1.08);
  }
  .pill-remove {
    font-size: 0.7rem;
    color: var(--text);
    opacity: 0.85;
  }
  .pill-empty {
    color: var(--text-dim);
    border-style: dashed;
    background: rgba(255,255,255,0.03);
    border-color: var(--border);
  }

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
  .play-btn {
    display: inline-flex;
    align-items: center;
    min-width: 58px;
    padding: 6px 10px;
    border-radius: 999px;
    border: 1px solid rgba(56, 189, 248, 0.28);
    background: rgba(56, 189, 248, 0.08);
    color: var(--accent);
    font-size: 0.72rem;
    font-weight: 700;
    justify-content: center;
  }
  .media-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 58px;
    padding: 6px 10px;
    border-radius: 999px;
    border: 1px solid rgba(96, 165, 250, 0.28);
    background: rgba(96, 165, 250, 0.08);
    color: var(--blue);
    font-size: 0.72rem;
    font-weight: 700;
    text-decoration: none;
  }
  .play-btn.is-loading {
    color: var(--text);
    border-color: rgba(148, 163, 184, 0.3);
  }
  .play-btn.is-playing {
    color: var(--orange);
    border-color: rgba(251, 146, 60, 0.32);
    background: rgba(251, 146, 60, 0.12);
  }
  .play-btn.is-error {
    color: var(--red);
    border-color: rgba(248, 113, 113, 0.32);
    background: rgba(248, 113, 113, 0.12);
  }
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
  .camera-shell {
    border: 1px solid var(--border);
    border-radius: 12px;
    background: var(--bg-dark);
    overflow: hidden;
  }
  .camera-frame {
    display: block;
    width: 100%;
    aspect-ratio: 16 / 9;
    object-fit: cover;
    background: #040814;
  }
  .camera-meta {
    margin-top: 10px;
    font-size: 0.75rem;
    color: var(--text-dim);
  }

  /* ── Log Viewer ─────────────────────────────────────── */
  .log-controls {
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
  }
  .log-search {
    min-width: 220px;
    flex: 1 1 240px;
    background: var(--bg-dark);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 8px 10px;
    border-radius: 8px;
    font-size: 0.8rem;
  }
  .log-check {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font-size: 0.75rem;
    color: var(--text-dim);
    white-space: nowrap;
  }
  .log-check input {
    accent-color: var(--accent);
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
  .footer-link {
    margin-top: 18px;
    text-align: center;
    font-size: 0.8rem;
    color: var(--text-dim);
  }
  .footer-link a {
    color: var(--accent);
    text-decoration: none;
    font-weight: 600;
  }
  .footer-link a:hover {
    text-decoration: underline;
  }
</style>
</head>
<body>

<div class="header">
  <h1>bark0matic <span class="header-badge">v{{ app_version }}</span></h1>
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
      <div class="stat">
        <div class="stat-label">Audio Level</div>
        <div class="meter-wrap">
          <div class="meter-bar"><div class="meter-fill" id="audio-meter-fill"></div></div>
          <div class="meter-meta">
            <span id="audio-meter-state">Silent</span>
            <span id="audio-meter-db">— dB</span>
          </div>
        </div>
      </div>
      <div class="stat">
        <div class="stat-label">Disk Free</div>
        <div class="stat-value" id="disk-free" style="font-size:1.1rem;">â€”</div>
        <div class="meter-meta">
          <span id="disk-free-pct">â€”</span>
          <span id="disk-total">â€”</span>
        </div>
      </div>
    </div>
    <div class="controls">
      <button class="btn-start" onclick="control('start')">&#9654; Start</button>
      <button class="btn-stop" onclick="control('stop')">&#9632; Stop</button>
    </div>
  </div>

  <div class="grid-2">

    <!-- ── Recording ───────────────────────────────────── -->
    <div class="card">
      <div class="card-header">
        <h2>Recording</h2>
      </div>
      <div class="field full-width">
        <label>Sounds To Record (up to 10)</label>
        <input type="text" id="record_sound_search" placeholder="Search YAMNet sounds..." oninput="filterRecordSounds()">
        <select id="record_sound_indices" multiple size="10" onchange="recordSoundsChanged()"></select>
        <div class="field-hint">Select multiple sounds with Ctrl + click (or Cmd + click on Mac), then press Save All Settings.<br>Click a selected tag to remove it.</div>
        <div class="pill-list" id="record-sound-pills">
          <span class="pill pill-empty">No sounds selected</span>
        </div>
        <div style="font-size:0.75rem; color:var(--text-dim); margin-top:8px;" id="record-sound-summary">No recording sounds selected</div>
        <div class="field-warning" id="recording-disk-warning">Recording is currently disabled because disk usage is at or above 95%. Use Free Disk Space to delete recordings and log entries older than 30 days.</div>
      </div>
      <p style="font-size:0.75rem; color:var(--text-dim); margin-top:10px;">
        Barkomatic logs every non-speech YAMNet sound above threshold. Audio is only saved when the most prominent detected sound is one of the selected sounds.
      </p>
    </div>

    <!-- ── Microphone ────────────────────────────────────── -->
    <div class="card">
      <div class="card-header">
        <h2>Camera Snapshot</h2>
        <button class="btn-clear" onclick="refreshCameraSnapshot()" style="padding:6px 12px; font-size:0.75rem;">Refresh</button>
      </div>
      <div class="camera-shell">
        <img id="camera-snapshot" class="camera-frame" alt="Live camera snapshot">
      </div>
      <div class="camera-meta" id="camera-status">Live snapshot refreshes every 8 seconds. Saved recordings also keep a matching snapshot.</div>
      <div class="camera-meta" id="camera-last-saved">Last saved snapshot: --</div>
    </div>

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
      <div class="field-subsection">
        <div class="card-header" style="margin-bottom:14px;">
          <h2>Thresholds</h2>
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
      </div>
    </div>

    <!-- ── Sensitivity ─────────────────────────────────── -->
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
      <div class="field-subsection">
        <div style="display:flex; align-items:center; gap:10px; margin-bottom:12px;">
          <label style="font-size:0.85rem; font-weight:600; color:var(--text);">Quiet Hours</label>
          <label style="display:flex; align-items:center; gap:6px; font-size:0.8rem; color:var(--text-dim); cursor:pointer;">
            <input type="checkbox" id="quiet_hours_enabled" style="accent-color:var(--accent); width:14px; height:14px;">
            Enable quiet hours enforcement
          </label>
        </div>
        <div class="settings-grid">
          <div class="field">
            <label>Weekday quiet start (HH:MM)</label>
            <input type="text" id="qh_weekday_start" placeholder="22:00" pattern="\d{2}:\d{2}">
          </div>
          <div class="field">
            <label>Weekday quiet end (HH:MM)</label>
            <input type="text" id="qh_weekday_end" placeholder="08:00" pattern="\d{2}:\d{2}">
          </div>
          <div class="field">
            <label>Weekend quiet start (HH:MM)</label>
            <input type="text" id="qh_weekend_start" placeholder="22:00" pattern="\d{2}:\d{2}">
          </div>
          <div class="field">
            <label>Weekend quiet end (HH:MM)</label>
            <input type="text" id="qh_weekend_end" placeholder="09:00" pattern="\d{2}:\d{2}">
          </div>
        </div>
        <div style="font-size:0.75rem; color:var(--text-dim); margin-top:4px;">NSW defaults: 10pm–8am weekdays, 10pm–9am weekends. Incidents within these windows are flagged as quiet hours violations.</div>
      </div>
    </div>
    <div style="margin-top:14px; display:flex; gap:10px;">
      <button class="btn-save" onclick="saveSettings()">Save All Settings</button>
      <button class="btn-update" onclick="updateSoftware()">&#10227; Update Software</button>
      <button class="btn-clear" onclick="freeDiskSpace()">Free Disk Space</button>
      <button class="btn-download" onclick="downloadCsv()">&#11015; Download CSV</button>
    </div>
  </div>

  <!-- ── Incidents ─────────────────────────────────────── -->
  <div class="card">
    <div class="card-header">
      <h2>Incidents</h2>
      <div class="log-controls">
        <select id="incident-event-type" onchange="fetchIncidents()" style="background:var(--bg-dark); border:1px solid var(--border); color:var(--text); padding:4px 8px; border-radius:6px; font-size:0.75rem;">
          <option value="">All types</option>
          <option value="dog_barking">Dog barking</option>
          <option value="amplified_music">Amplified music</option>
          <option value="shouting">Shouting</option>
          <option value="impact_banging">Impact / banging</option>
          <option value="sustained_loud_noise">Sustained loud noise</option>
          <option value="unknown_nuisance_noise">Unknown nuisance</option>
        </select>
        <select id="incident-review-status" onchange="fetchIncidents()" style="background:var(--bg-dark); border:1px solid var(--border); color:var(--text); padding:4px 8px; border-radius:6px; font-size:0.75rem;">
          <option value="">All statuses</option>
          <option value="pending">Pending</option>
          <option value="reviewed">Reviewed</option>
          <option value="dismissed">Dismissed</option>
        </select>
        <select id="incident-limit" onchange="fetchIncidents()" style="background:var(--bg-dark); border:1px solid var(--border); color:var(--text); padding:4px 8px; border-radius:6px; font-size:0.75rem;">
          <option value="25">Last 25</option>
          <option value="50" selected>Last 50</option>
          <option value="100">Last 100</option>
        </select>
        <label class="log-check">
          <input type="checkbox" id="incident-qh-only" onchange="fetchIncidents()" style="accent-color:var(--accent);">
          <span style="color:var(--orange); font-weight:600;">&#9679;</span> QH violations only
        </label>
        <input type="date" id="incident-date-from" title="From date" onchange="fetchIncidents()" style="background:var(--bg-dark); border:1px solid var(--border); color:var(--text); padding:4px 6px; border-radius:6px; font-size:0.75rem;">
        <input type="date" id="incident-date-to" title="To date" onchange="fetchIncidents()" style="background:var(--bg-dark); border:1px solid var(--border); color:var(--text); padding:4px 6px; border-radius:6px; font-size:0.75rem;">
        <button onclick="exportIncidents('csv')" style="background:var(--bg-dark); border:1px solid var(--border); color:var(--text); padding:4px 10px; border-radius:6px; font-size:0.75rem; cursor:pointer;" title="Export Report (CSV)">&#11015; CSV</button>
        <button onclick="exportIncidents('pdf')" style="background:var(--bg-dark); border:1px solid var(--accent); color:var(--accent); padding:4px 10px; border-radius:6px; font-size:0.75rem; cursor:pointer; font-weight:600;" title="Export Report (PDF)">&#11015; PDF</button>
        <span class="log-count" id="incident-count"></span>
      </div>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Started</th>
            <th>Type</th>
            <th>Duration</th>
            <th>Peak dB</th>
            <th>Avg dB</th>
            <th>Confidence</th>
            <th>Severity</th>
            <th>Detections</th>
            <th title="Quiet Hours Violation">QH</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody id="incidents"></tbody>
      </table>
      <div class="empty-state" id="incidents-empty-state">
        <div style="font-size:2rem; margin-bottom:8px;">&#128203;</div>
        <p>No incidents yet. Detections will be grouped into incidents automatically.</p>
      </div>
    </div>
  </div>

  <!-- ── Detections Log ────────────────────────────────── -->
  <div class="card">
    <div class="card-header">
      <h2>Detection Log</h2>
      <div class="log-controls">
        <input id="log-search" class="log-search" type="text" placeholder="Filter by sound or timestamp..." oninput="fetchDetections()">
        <label class="log-check"><input id="log-audio-only" type="checkbox" onchange="fetchDetections()"> Recorded clips only</label>
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
            <th>Snapshot</th>
            <th>Timestamp</th>
            <th>Sound</th>
            <th>Decibels</th>
            <th>Frequency</th>
            <th>Confidence</th>
            <th>Duration</th>
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

  <div class="footer-link">
    <a href="/changelog" target="_blank" rel="noopener noreferrer">View changelog</a>
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
let availableSounds = [];
let selectedRecordSoundIndices = [];
let cameraRefreshTimer = null;

let currentAudio = null;
let currentBtn = null;
function setPlayButtonState(btn, state) {
  if (!btn) return;
  btn.classList.remove('is-loading', 'is-playing', 'is-error');
  if (state === 'loading') {
    btn.classList.add('is-loading');
    btn.textContent = '...';
    return;
  }
  if (state === 'playing') {
    btn.classList.add('is-playing');
    btn.textContent = 'Stop';
    return;
  }
  if (state === 'error') {
    btn.classList.add('is-error');
    btn.textContent = 'Error';
    return;
  }
  btn.textContent = 'Play';
}

function playAudio(filename, btn) {
  if (currentAudio) {
    if (currentBtn === btn) {
      currentAudio.pause();
      currentAudio = null;
      setPlayButtonState(currentBtn, 'idle');
      currentBtn = null;
      return;
    }
    currentAudio.pause();
    currentAudio = null;
    setPlayButtonState(currentBtn, 'idle');
  }
  setPlayButtonState(btn, 'loading');
  const audio = new Audio('/api/audio/' + encodeURIComponent(filename));
  audio.oncanplay = () => { setPlayButtonState(btn, 'playing'); };
  audio.onended = () => { setPlayButtonState(btn, 'idle'); currentAudio = null; currentBtn = null; };
  audio.onerror = () => {
    setPlayButtonState(btn, 'error');
    setTimeout(() => setPlayButtonState(btn, 'idle'), 2000);
  };
  audio.play().catch(e => {
    setPlayButtonState(btn, 'error');
    setTimeout(() => setPlayButtonState(btn, 'idle'), 2000);
    console.error('Playback failed:', e);
  });
  currentAudio = audio;
  currentBtn = btn;
}

function confColor(c) {
  const v = parseFloat(c) || 0;
  if (v >= 0.7) return 'var(--green)';
  if (v >= 0.4) return 'var(--orange)';
  return 'var(--red)';
}

function audioMeterPercent(db) {
  const value = parseFloat(db);
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, ((value + 80) / 80) * 100));
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
    document.getElementById('header-status').textContent = d.running ? 'Listening for all sounds' : 'Stopped';
    document.getElementById('header-status').style.color = d.running ? 'var(--green)' : 'var(--red)';
    const dot = document.getElementById('header-dot');
    dot.className = 'pulse-dot ' + (d.running ? 'running' : 'stopped');
    const meterPct = audioMeterPercent(d.last_audio_db);
    document.getElementById('audio-meter-fill').style.width = meterPct + '%';
    document.getElementById('audio-meter-state').textContent = d.audio_present ? 'Audio detected' : 'Silent';
    document.getElementById('audio-meter-state').style.color = d.audio_present ? 'var(--green)' : 'var(--text-dim)';
    document.getElementById('audio-meter-db').textContent =
      Number.isFinite(parseFloat(d.last_audio_db)) ? (d.last_audio_db + ' dB') : '— dB';

    if (d.last_detection) {
      const ld = d.last_detection;
      document.getElementById('last-detection').textContent =
        (ld.sound_type || 'Sound') + ' • ' + ld.timestamp + ' (' + ld.decibels + 'dB)';
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

    // Advanced fields
    document.getElementById('min_frequency').value = d.min_frequency;
    document.getElementById('max_frequency').value = d.max_frequency;
    document.getElementById('chunk_size').value = d.chunk_size;
    document.getElementById('local_timezone').value = d.local_timezone || '';
    document.getElementById('mic_device_adv').value = d.microphone_device;

    // Quiet hours
    document.getElementById('quiet_hours_enabled').checked = !!d.quiet_hours_enabled;
    const qhwd = d.quiet_hours_weekday || {};
    const qhwe = d.quiet_hours_weekend || {};
    document.getElementById('qh_weekday_start').value = qhwd.start || '22:00';
    document.getElementById('qh_weekday_end').value = qhwd.end || '08:00';
    document.getElementById('qh_weekend_start').value = qhwe.start || '22:00';
    document.getElementById('qh_weekend_end').value = qhwe.end || '09:00';

    availableSounds = d.available_sounds || [];
    selectedRecordSoundIndices = (d.record_sound_indices || []).map(v => String(v));
    renderRecordSoundOptions();
  } catch(e) { console.error(e); }
}

function renderRecordSoundOptions() {
  const selected = new Set(selectedRecordSoundIndices);
  const search = (document.getElementById('record_sound_search')?.value || '').trim().toLowerCase();
  const sounds = availableSounds.filter(item => !search || item.name.toLowerCase().includes(search));
  const sel = document.getElementById('record_sound_indices');
  sel.innerHTML = sounds.map(item =>
    `<option value="${item.index}" ${selected.has(String(item.index)) ? 'selected' : ''}>${item.name}</option>`
  ).join('');
  updateRecordSoundSummary();
}

function filterRecordSounds() {
  renderRecordSoundOptions();
}

function recordSoundsChanged() {
  const sel = document.getElementById('record_sound_indices');
  const visibleSelected = Array.from(sel.selectedOptions).map(opt => String(opt.value));
  const visibleValues = new Set(Array.from(sel.options).map(opt => String(opt.value)));
  const retained = selectedRecordSoundIndices.filter(value => !visibleValues.has(String(value)));
  const merged = retained.concat(visibleSelected.filter(value => !retained.includes(value)));

  if (merged.length > 10) {
    const lastValue = merged[merged.length - 1];
    const lastOption = Array.from(sel.options).find(opt => String(opt.value) === lastValue);
    if (lastOption) lastOption.selected = false;
    showToast('You can record up to 10 sounds', 'error');
    return;
  }
  selectedRecordSoundIndices = merged;
  updateRecordSoundSummary();
  showToast('Recording selection changed. Click Save All Settings to apply it.', 'success');
}

function updateRecordSoundSummary() {
  const summary = document.getElementById('record-sound-summary');
  const pills = document.getElementById('record-sound-pills');
  const selected = selectedRecordSoundIndices
    .map(value => availableSounds.find(item => String(item.index) === String(value)))
    .filter(Boolean);

  pills.innerHTML = selected.length
    ? selected.map(item => `<button type="button" class="pill pill-button" onclick="removeRecordSound('${item.index}')" title="Remove ${item.name}">${item.name}<span class="pill-remove">x</span></button>`).join('')
    : '<span class="pill pill-empty">No sounds selected</span>';

  summary.textContent = selected.length
    ? (selected.length + ' selected: ' + selected.map(item => item.name).join(', ') + ' | Click Save All Settings to apply changes')
    : 'No recording sounds selected | Click Save All Settings to apply changes';
}

function removeRecordSound(index) {
  selectedRecordSoundIndices = selectedRecordSoundIndices.filter(value => String(value) !== String(index));
  renderRecordSoundOptions();
  showToast('Recording selection changed. Click Save All Settings to apply it.', 'success');
}

async function saveSettings() {
  const data = {
    threshold: parseFloat(document.getElementById('threshold').value),
    energy_threshold: parseFloat(document.getElementById('energy_threshold').value),
    min_frequency: parseFloat(document.getElementById('min_frequency').value),
    max_frequency: parseFloat(document.getElementById('max_frequency').value),
    chunk_size: parseFloat(document.getElementById('chunk_size').value),
    local_timezone: document.getElementById('local_timezone').value.trim(),
    record_sound_indices: selectedRecordSoundIndices.map(value => parseInt(value, 10)),
    quiet_hours_enabled: document.getElementById('quiet_hours_enabled').checked,
    quiet_hours_weekday: {
      start: document.getElementById('qh_weekday_start').value.trim() || '22:00',
      end: document.getElementById('qh_weekday_end').value.trim() || '08:00',
    },
    quiet_hours_weekend: {
      start: document.getElementById('qh_weekend_start').value.trim() || '22:00',
      end: document.getElementById('qh_weekend_end').value.trim() || '09:00',
    },
  };
  try {
    await fetch('/api/settings', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data)
    });
    setTimeout(fetchStatus, 500);
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

async function waitForReconnect(timeoutMs = 90000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    try {
      const res = await fetch('/api/status', {cache: 'no-store'});
      if (res.ok) {
        await fetchStatus();
        await fetchDetections();
        return true;
      }
    } catch (e) {
      // Service is expected to be unavailable while restarting.
    }
    await new Promise(resolve => setTimeout(resolve, 2000));
  }
  return false;
}

async function updateSoftware() {
  if (!confirm('Pull the latest version from GitHub and restart Barkomatic now?')) return;

  try {
    const res = await fetch('/api/update', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'}
    });
    const data = await res.json();

    if (!res.ok || data.status !== 'started') {
      throw new Error(data.message || 'Update failed to start');
    }

    showToast('Update started. Waiting for restart...', 'success');
    const reconnected = await waitForReconnect();
    if (reconnected) {
      showToast('Update complete. Barkomatic is back online.', 'success');
    } else {
      showToast('Update started, but reconnect timed out. Refresh in a minute.', 'error');
    }
  } catch (e) {
    showToast('Failed to start update: ' + e.message, 'error');
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

function currentLogFilters() {
  return {
    count: document.getElementById('log-limit').value,
    search: document.getElementById('log-search').value.trim(),
    audio_only: document.getElementById('log-audio-only').checked ? '1' : '0',
  };
}

function downloadCsv() {
  window.location.href = '/api/download?' + new URLSearchParams(currentLogFilters()).toString();
}

function renderSnapshotCell(snapshotFile) {
  if (!snapshotFile) {
    return '<span style="color:var(--text-dim); font-size:0.7rem;">--</span>';
  }
  return `<a class="media-btn" href="/api/snapshot/${encodeURIComponent(snapshotFile)}" target="_blank" rel="noopener noreferrer">View</a>`;
}

function refreshCameraSnapshot() {
  const image = document.getElementById('camera-snapshot');
  const status = document.getElementById('camera-status');
  status.textContent = 'Refreshing live camera snapshot...';
  image.src = '/api/camera/live?ts=' + Date.now();
}

function initCameraSnapshot() {
  const image = document.getElementById('camera-snapshot');
  const status = document.getElementById('camera-status');
  image.onload = () => {
    status.textContent = 'Live snapshot refreshes every 8 seconds. Saved recordings also keep a matching snapshot.';
  };
  image.onerror = () => {
    status.textContent = 'Camera snapshot unavailable. Check camera setup on the Pi.';
  };
  refreshCameraSnapshot();
  if (cameraRefreshTimer) {
    clearInterval(cameraRefreshTimer);
  }
  cameraRefreshTimer = setInterval(refreshCameraSnapshot, 8000);
}

async function fetchStatus() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    const el = document.getElementById('state');
    el.textContent = d.running ? 'Listening' : 'Stopped';
    el.className = 'stat-value ' + (d.running ? 'running' : 'stopped');
    document.getElementById('sound-type').textContent = d.sound_type || 'â€”';
    document.getElementById('count').textContent = d.total_logged || 0;
    document.getElementById('uptime').textContent = d.uptime || 'â€”';
    document.getElementById('header-status').textContent = d.running ? 'Listening for all sounds' : 'Stopped';
    document.getElementById('header-status').style.color = d.running ? 'var(--green)' : 'var(--red)';
    const dot = document.getElementById('header-dot');
    dot.className = 'pulse-dot ' + (d.running ? 'running' : 'stopped');
    const meterPct = audioMeterPercent(d.last_audio_db);
    document.getElementById('audio-meter-fill').style.width = meterPct + '%';
    document.getElementById('audio-meter-state').textContent = d.audio_present ? 'Audio detected' : 'Silent';
    document.getElementById('audio-meter-state').style.color = d.audio_present ? 'var(--green)' : 'var(--text-dim)';
    document.getElementById('audio-meter-db').textContent =
      Number.isFinite(parseFloat(d.last_audio_db)) ? (d.last_audio_db + ' dB') : 'â€” dB';
    document.getElementById('disk-free').textContent =
      Number.isFinite(parseFloat(d.disk_free_gb)) ? (d.disk_free_gb + ' GB') : 'â€”';
    document.getElementById('disk-free-pct').textContent =
      Number.isFinite(parseFloat(d.disk_free_pct)) ? (d.disk_free_pct + '% free') : 'â€”';
    document.getElementById('disk-total').textContent =
      Number.isFinite(parseFloat(d.disk_total_gb)) ? ('of ' + d.disk_total_gb + ' GB') : 'â€”';

    if (d.last_detection) {
      const ld = d.last_detection;
      document.getElementById('last-detection').textContent =
        (ld.sound_type || 'Sound') + ' â€¢ ' + ld.timestamp + ' (' + ld.decibels + 'dB)';
    }
  } catch(e) {
    document.getElementById('header-status').textContent = 'Connection error';
    document.getElementById('header-status').style.color = 'var(--red)';
  }
}

async function freeDiskSpace() {
  if (!confirm('Delete recordings, saved snapshots, and log entries older than 30 days to free disk space?')) return;

  try {
    const res = await fetch('/api/free-disk-space', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'}
    });
    const data = await res.json();

    if (!res.ok || data.status !== 'ok') {
      throw new Error(data.message || 'Cleanup failed');
    }

    await fetchStatus();
    await fetchDetections();
    showToast(
      'Deleted ' + data.deleted_files + ' old media file(s) and ' + data.deleted_logs + ' log(s), freed ' + data.freed_mb + ' MB',
      'success'
    );
  } catch (e) {
    showToast('Failed to free disk space: ' + e.message, 'error');
  }
}

async function fetchStatus() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    const el = document.getElementById('state');
    el.textContent = d.running ? 'Listening' : 'Stopped';
    el.className = 'stat-value ' + (d.running ? 'running' : 'stopped');
    document.getElementById('sound-type').textContent = d.sound_type || '--';
    document.getElementById('count').textContent = d.total_logged || 0;
    document.getElementById('uptime').textContent = d.uptime || '--';
    document.getElementById('header-status').textContent = d.running ? 'Listening for all sounds' : 'Stopped';
    document.getElementById('header-status').style.color = d.running ? 'var(--green)' : 'var(--red)';
    const dot = document.getElementById('header-dot');
    dot.className = 'pulse-dot ' + (d.running ? 'running' : 'stopped');
    const meterPct = audioMeterPercent(d.last_audio_db);
    document.getElementById('audio-meter-fill').style.width = meterPct + '%';
    document.getElementById('audio-meter-state').textContent = d.audio_present ? 'Audio detected' : 'Silent';
    document.getElementById('audio-meter-state').style.color = d.audio_present ? 'var(--green)' : 'var(--text-dim)';
    document.getElementById('audio-meter-db').textContent =
      Number.isFinite(parseFloat(d.last_audio_db)) ? (d.last_audio_db + ' dB') : '-- dB';
    document.getElementById('disk-free').textContent =
      Number.isFinite(parseFloat(d.disk_free_gb)) ? (d.disk_free_gb + ' GB') : '--';
    document.getElementById('disk-free-pct').textContent =
      Number.isFinite(parseFloat(d.disk_free_pct)) ? (d.disk_free_pct + '% free') : '--';
    document.getElementById('disk-total').textContent =
      Number.isFinite(parseFloat(d.disk_total_gb)) ? ('of ' + d.disk_total_gb + ' GB') : '--';
    document.getElementById('disk-free').style.color = d.recording_blocked_low_disk ? 'var(--red)' : '';
    document.getElementById('disk-free-pct').style.color = d.recording_blocked_low_disk ? 'var(--red)' : '';
    document.getElementById('recording-disk-warning').style.display =
      d.recording_blocked_low_disk ? 'block' : 'none';
    document.getElementById('camera-last-saved').textContent =
      'Last saved snapshot: ' + (d.last_snapshot_file || '--');
    if (d.camera_available === false) {
      document.getElementById('camera-status').textContent = 'Camera snapshot unavailable. Check camera setup on the Pi.';
    }

    if (d.last_detection) {
      const ld = d.last_detection;
      document.getElementById('last-detection').textContent =
        (ld.sound_type || 'Sound') + ' | ' + ld.timestamp + ' (' + ld.decibels + 'dB)';
    }
  } catch (e) {
    document.getElementById('header-status').textContent = 'Connection error';
    document.getElementById('header-status').style.color = 'var(--red)';
  }
}

async function fetchDetections() {
  try {
    const filters = currentLogFilters();
    const r = await fetch('/api/detections?' + new URLSearchParams(filters).toString());
    const rows = await r.json();
    const tbody = document.getElementById('detections');
    const empty = document.getElementById('empty-state');

    if (rows.length === 0) {
      tbody.innerHTML = '';
      empty.style.display = 'block';
      empty.querySelector('p').textContent = filters.search || filters.audio_only === '1'
        ? 'No detections match the current filters.'
        : 'No detections yet. Listening...';
      document.getElementById('log-count').textContent = '';
      return;
    }
    empty.style.display = 'none';
    document.getElementById('log-count').textContent = rows.length + ' matching events';

    tbody.innerHTML = rows.map(r => {
      const conf = parseFloat(r.confidence) || 0;
      const pct = Math.min(conf * 100, 100);
      const playBtn = r.audio_file
        ? `<button class="play-btn" onclick="playAudio('${r.audio_file}', this)" title="Play recording">Play</button>`
        : '<span style="color:var(--text-dim); font-size:0.7rem;">â€”</span>';
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
      </tr>`;
    }).join('');
  } catch(e) { console.error(e); }
}

async function fetchDetections() {
  try {
    const filters = currentLogFilters();
    const r = await fetch('/api/detections?' + new URLSearchParams(filters).toString());
    const rows = await r.json();
    const tbody = document.getElementById('detections');
    const empty = document.getElementById('empty-state');

    if (rows.length === 0) {
      tbody.innerHTML = '';
      empty.style.display = 'block';
      empty.querySelector('p').textContent = filters.search || filters.audio_only === '1'
        ? 'No detections match the current filters.'
        : 'No detections yet. Listening...';
      document.getElementById('log-count').textContent = '';
      return;
    }
    empty.style.display = 'none';
    document.getElementById('log-count').textContent = rows.length + ' matching events';

    tbody.innerHTML = rows.map(r => {
      const conf = parseFloat(r.confidence) || 0;
      const pct = Math.min(conf * 100, 100);
      const playBtn = r.audio_file
        ? `<button class="play-btn" onclick="playAudio('${r.audio_file}', this)" title="Play recording">Play</button>`
        : '<span style="color:var(--text-dim); font-size:0.7rem;">--</span>';
      const snapshotBtn = renderSnapshotCell(r.snapshot_file);
      return `<tr>
        <td>${playBtn}</td>
        <td>${snapshotBtn}</td>
        <td style="white-space:nowrap;">${r.timestamp || ''}</td>
        <td>${r.sound_type || ''}</td>
        <td>${r.decibels || ''}dB</td>
        <td>${r.frequency_hz || ''}Hz</td>
        <td>
          <span class="confidence-bar"><span class="confidence-fill" style="width:${pct}%; background:${confColor(r.confidence)};"></span></span>
          ${r.confidence || ''}
        </td>
        <td>${r.duration_seconds || ''}s</td>
      </tr>`;
    }).join('');
  } catch (e) { console.error(e); }
}

function currentIncidentFilters() {
  const eventType = document.getElementById('incident-event-type').value;
  const reviewStatus = document.getElementById('incident-review-status').value;
  const limit = document.getElementById('incident-limit').value;
  const dateFrom = document.getElementById('incident-date-from').value;
  const dateTo = document.getElementById('incident-date-to').value;
  const params = new URLSearchParams({ count: limit });
  if (eventType) params.set('event_type', eventType);
  if (reviewStatus) params.set('review_status', reviewStatus);
  if (dateFrom) params.set('date_from', dateFrom);
  if (dateTo) params.set('date_to', dateTo);
  return params;
}

function exportIncidents(format) {
  const params = currentIncidentFilters();
  params.set('count', '10000');
  window.location.href = '/api/export/incidents.' + format + '?' + params.toString();
}

async function fetchIncidents() {
  try {
    const qhOnly = document.getElementById('incident-qh-only').checked;
    const params = currentIncidentFilters();
    const r = await fetch('/api/incidents?' + params.toString());
    let rows = await r.json();
    if (qhOnly) rows = rows.filter(inc => inc.quiet_hours_violation);
    const tbody = document.getElementById('incidents');
    const empty = document.getElementById('incidents-empty-state');

    if (!rows.length) {
      tbody.innerHTML = '';
      empty.style.display = 'block';
      document.getElementById('incident-count').textContent = '';
      return;
    }
    empty.style.display = 'none';
    const qhCount = rows.filter(inc => inc.quiet_hours_violation).length;
    document.getElementById('incident-count').textContent = rows.length + ' incidents' + (qhCount ? ` · ${qhCount} QH` : '');

    const severityColor = s => {
      if (s >= 0.7) return 'var(--red)';
      if (s >= 0.4) return 'var(--orange)';
      return 'var(--green)';
    };
    const statusBadge = st => {
      const colors = { pending: 'var(--orange)', reviewed: 'var(--green)', dismissed: 'var(--text-dim)' };
      return `<span style="color:${colors[st] || 'var(--text)'}; font-size:0.75rem;">${st}</span>`;
    };
    const qhBadge = v => v
      ? `<span title="Quiet Hours Violation" style="color:var(--orange); font-weight:700; font-size:0.85rem;">&#9679;</span>`
      : `<span style="color:var(--border);">&#8212;</span>`;

    tbody.innerHTML = rows.map(inc => {
      const sev = parseFloat(inc.severity_score) || 0;
      const sevPct = Math.min(sev * 100, 100);
      const rowBg = inc.quiet_hours_violation ? 'background:rgba(251,146,60,0.04);' : '';
      const playBtn = inc.media_ref
        ? `<button class="play-btn" onclick="playAudio('${inc.media_ref}', this)" title="Play clip">Play</button>`
        : '';
      return `<tr style="${rowBg}">
        <td style="white-space:nowrap; font-size:0.8rem;">${inc.started_at || ''}</td>
        <td style="font-size:0.8rem;">${(inc.event_type || '').replace(/_/g,' ')}</td>
        <td style="font-size:0.8rem;">${inc.duration_seconds}s</td>
        <td style="font-size:0.8rem;">${inc.peak_db}dB</td>
        <td style="font-size:0.8rem;">${inc.average_db}dB</td>
        <td style="font-size:0.8rem;">${inc.confidence}</td>
        <td>
          <span class="confidence-bar"><span class="confidence-fill" style="width:${sevPct}%; background:${severityColor(sev)};"></span></span>
          <span style="font-size:0.75rem; color:${severityColor(sev)};">${sev}</span>
        </td>
        <td style="font-size:0.8rem; text-align:center;">${inc.detection_count}</td>
        <td style="text-align:center;">${qhBadge(inc.quiet_hours_violation)}</td>
        <td>${statusBadge(inc.review_status)}</td>
        <td style="white-space:nowrap;">
          ${playBtn}
          <button onclick="reviewIncident('${inc.incident_id}','reviewed')" style="font-size:0.7rem; padding:2px 6px; background:var(--green-bg); color:var(--green); border:1px solid var(--green); border-radius:4px; cursor:pointer; margin:1px;">&#10003;</button>
          <button onclick="reviewIncident('${inc.incident_id}','dismissed')" style="font-size:0.7rem; padding:2px 6px; background:var(--red-bg); color:var(--red); border:1px solid var(--red); border-radius:4px; cursor:pointer; margin:1px;">&times;</button>
        </td>
      </tr>`;
    }).join('');
  } catch(e) { console.error(e); }
}

async function reviewIncident(incidentId, status) {
  try {
    await fetch('/api/incidents/' + incidentId, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ review_status: status }),
    });
    fetchIncidents();
  } catch(e) { console.error(e); }
}

loadSettings();
fetchStatus();
fetchIncidents();
fetchDetections();
detectMics(true);
initCameraSnapshot();
setInterval(fetchStatus, 3000);
setInterval(fetchDetections, 5000);
setInterval(fetchIncidents, 15000);
</script>
</body>
</html>"""

# ---------------------------------------------------------------------------
# Officer portal HTML templates
# ---------------------------------------------------------------------------

PORTAL_LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sentinel — Officer Login</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#0b1120;color:#e2e8f0;font-family:system-ui,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh}
  .card{background:#151d2e;border:1px solid #1e2d45;border-radius:12px;padding:2rem;width:100%;max-width:380px}
  h1{font-size:1.3rem;font-weight:700;margin-bottom:.25rem;color:#f1f5f9}
  .sub{color:#64748b;font-size:.85rem;margin-bottom:1.5rem}
  label{display:block;font-size:.8rem;color:#94a3b8;margin-bottom:.35rem}
  input{width:100%;background:#0b1120;border:1px solid #1e2d45;border-radius:6px;color:#e2e8f0;padding:.6rem .75rem;font-size:.9rem;outline:none}
  input:focus{border-color:#38bdf8}
  .field{margin-bottom:1rem}
  .btn{width:100%;background:#0ea5e9;color:#fff;border:none;border-radius:6px;padding:.7rem;font-size:.95rem;font-weight:600;cursor:pointer;margin-top:.5rem}
  .btn:hover{background:#0284c7}
  .error{background:#7f1d1d;border:1px solid #ef4444;border-radius:6px;padding:.6rem .75rem;font-size:.85rem;color:#fca5a5;margin-bottom:1rem}
  .badge{display:inline-block;background:#0ea5e920;color:#38bdf8;border-radius:4px;padding:.15rem .5rem;font-size:.75rem;font-weight:600;margin-bottom:1rem}
</style>
</head>
<body>
<div class="card">
  <div class="badge">COUNCIL OFFICER PORTAL</div>
  <h1>Sentinel</h1>
  <div class="sub">Sign in to review complaint cases</div>
  {% if error %}<div class="error">{{ error }}</div>{% endif %}
  <form method="post">
    <div class="field">
      <label>Username</label>
      <input type="text" name="username" autocomplete="username" required autofocus>
    </div>
    <div class="field">
      <label>Password</label>
      <input type="password" name="password" autocomplete="current-password" required>
    </div>
    <button class="btn" type="submit">Sign in</button>
  </form>
</div>
</body>
</html>"""


PORTAL_CASES_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sentinel — Case List</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#0b1120;color:#e2e8f0;font-family:system-ui,sans-serif;padding:1.5rem}
  header{display:flex;align-items:center;justify-content:space-between;margin-bottom:1.5rem;gap:1rem;flex-wrap:wrap}
  h1{font-size:1.2rem;font-weight:700}
  .sub{color:#64748b;font-size:.85rem}
  .badge{display:inline-block;background:#0ea5e920;color:#38bdf8;border-radius:4px;padding:.15rem .5rem;font-size:.75rem;font-weight:600;margin-right:.5rem}
  .actions{display:flex;gap:.5rem;align-items:center}
  a.btn-sm{background:#1e2d45;color:#94a3b8;border-radius:6px;padding:.4rem .8rem;font-size:.8rem;text-decoration:none}
  a.btn-sm:hover{background:#263548;color:#e2e8f0}
  form.logout button{background:transparent;color:#64748b;border:1px solid #1e2d45;border-radius:6px;padding:.4rem .8rem;font-size:.8rem;cursor:pointer}
  form.logout button:hover{color:#e2e8f0;border-color:#94a3b8}
  table{width:100%;border-collapse:collapse;font-size:.85rem}
  th{text-align:left;color:#64748b;font-weight:500;padding:.6rem .75rem;border-bottom:1px solid #1e2d45;white-space:nowrap}
  td{padding:.65rem .75rem;border-bottom:1px solid #1a2540;vertical-align:middle}
  tr:hover td{background:#111827}
  a.case-link{color:#38bdf8;text-decoration:none;font-weight:600}
  a.case-link:hover{text-decoration:underline}
  .pill{display:inline-block;border-radius:999px;padding:.2rem .6rem;font-size:.75rem;font-weight:600}
  .pill-pending{background:#78350f40;color:#fbbf24}
  .pill-reviewed{background:#14532d40;color:#4ade80}
  .empty{color:#475569;font-size:.9rem;padding:2rem 0}
  .card{background:#151d2e;border:1px solid #1e2d45;border-radius:10px;overflow:hidden}
</style>
</head>
<body>
<header>
  <div>
    <span class="badge">OFFICER PORTAL</span>
    <h1>Case List</h1>
    <div class="sub">{{ property_address }}</div>
  </div>
  <div class="actions">
    <a class="btn-sm" href="{{ url_for('portal_settings') }}">Settings</a>
    <form class="logout" method="post" action="{{ url_for('portal_logout') }}">
      <button type="submit">Sign out</button>
    </form>
  </div>
</header>
<div class="card">
{% if cases %}
<table>
  <thead>
    <tr>
      <th>Case ID</th>
      <th>Device</th>
      <th>Monitoring start</th>
      <th>Monitoring end</th>
      <th>Incidents</th>
      <th>Quiet hours violations</th>
      <th>Status</th>
    </tr>
  </thead>
  <tbody>
  {% for c in cases %}
    <tr>
      <td>
        {% if c.case_id %}
          <a class="case-link" href="{{ url_for('portal_case_detail', case_id=c.case_id) }}">{{ c.case_id }}</a>
        {% else %}
          <a class="case-link" href="{{ url_for('portal_case_detail', case_id='unassigned') }}">— Unassigned —</a>
        {% endif %}
      </td>
      <td>{{ c.device_id or '—' }}</td>
      <td>{{ c.monitoring_start[:16] if c.monitoring_start else '—' }}</td>
      <td>{{ c.monitoring_end[:16] if c.monitoring_end else '—' }}</td>
      <td>{{ c.total_incidents }}</td>
      <td>{{ c.quiet_hours_violations }}</td>
      <td>
        <span class="pill pill-{{ c.status }}">{{ c.status }}</span>
      </td>
    </tr>
  {% endfor %}
  </tbody>
</table>
{% else %}
  <div class="empty" style="padding:2rem 1rem">No cases found. Incidents must have a case_id assigned to appear here.</div>
{% endif %}
</div>
</body>
</html>"""


PORTAL_CASE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sentinel — Case {{ case_id }}</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#0b1120;color:#e2e8f0;font-family:system-ui,sans-serif;padding:1.5rem}
  header{display:flex;align-items:center;justify-content:space-between;margin-bottom:1.5rem;gap:1rem;flex-wrap:wrap}
  h1{font-size:1.2rem;font-weight:700}
  .sub{color:#64748b;font-size:.85rem}
  .badge{display:inline-block;background:#0ea5e920;color:#38bdf8;border-radius:4px;padding:.15rem .5rem;font-size:.75rem;font-weight:600;margin-right:.5rem}
  .actions{display:flex;gap:.5rem;align-items:center;flex-wrap:wrap}
  a.btn{background:#0ea5e9;color:#fff;border-radius:6px;padding:.5rem 1rem;font-size:.85rem;font-weight:600;text-decoration:none}
  a.btn:hover{background:#0284c7}
  a.btn-sm{background:#1e2d45;color:#94a3b8;border-radius:6px;padding:.4rem .8rem;font-size:.8rem;text-decoration:none}
  a.btn-sm:hover{background:#263548;color:#e2e8f0}
  form.logout button{background:transparent;color:#64748b;border:1px solid #1e2d45;border-radius:6px;padding:.4rem .8rem;font-size:.8rem;cursor:pointer}
  form.logout button:hover{color:#e2e8f0;border-color:#94a3b8}
  .stats-row{display:flex;gap:1rem;flex-wrap:wrap;margin-bottom:1.5rem}
  .stat{background:#151d2e;border:1px solid #1e2d45;border-radius:10px;padding:1rem 1.25rem;flex:1;min-width:140px}
  .stat-val{font-size:1.6rem;font-weight:700;color:#f1f5f9}
  .stat-lbl{font-size:.75rem;color:#64748b;margin-top:.15rem}
  .card{background:#151d2e;border:1px solid #1e2d45;border-radius:10px;overflow:hidden;margin-bottom:1.5rem}
  .card-title{padding:.75rem 1rem;border-bottom:1px solid #1e2d45;font-size:.85rem;font-weight:600;color:#94a3b8}
  table{width:100%;border-collapse:collapse;font-size:.82rem}
  th{text-align:left;color:#64748b;font-weight:500;padding:.55rem .75rem;border-bottom:1px solid #1e2d45;white-space:nowrap}
  td{padding:.6rem .75rem;border-bottom:1px solid #1a2540;vertical-align:middle}
  tr:hover td{background:#111827}
  .pill{display:inline-block;border-radius:999px;padding:.2rem .55rem;font-size:.72rem;font-weight:600}
  .pill-pending{background:#78350f40;color:#fbbf24}
  .pill-reviewed{background:#14532d40;color:#4ade80}
  .pill-dismissed{background:#1e293b;color:#64748b}
  select.status-sel{background:#0b1120;color:#e2e8f0;border:1px solid #1e2d45;border-radius:4px;padding:.2rem .4rem;font-size:.8rem;cursor:pointer}
  .heatmap{display:flex;flex-direction:column;gap:.5rem;padding:1rem}
  .heatmap-row{display:flex;align-items:center;gap:.4rem}
  .heatmap-lbl{font-size:.72rem;color:#64748b;width:2.5rem;text-align:right;flex-shrink:0}
  .heatmap-bars{display:flex;gap:2px;flex:1}
  .heatmap-bar{flex:1;border-radius:2px;min-height:18px;transition:opacity .15s}
  .type-row{display:flex;justify-content:space-between;padding:.5rem 1rem;font-size:.82rem;border-bottom:1px solid #1a2540}
  .type-row:last-child{border-bottom:none}
  .severity-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:.4rem;vertical-align:middle}
</style>
</head>
<body>
<header>
  <div>
    <span class="badge">OFFICER PORTAL</span>
    <h1>Case: {{ case_id }}</h1>
    <div class="sub">{{ property_address }}</div>
  </div>
  <div class="actions">
    {% if total > 0 %}
    <a class="btn" href="{{ url_for('portal_case_report_pdf', case_id=case_id) }}">Generate Case Report (PDF)</a>
    {% endif %}
    <a class="btn-sm" href="{{ url_for('portal_cases') }}">← All cases</a>
    <form class="logout" method="post" action="{{ url_for('portal_logout') }}">
      <button type="submit">Sign out</button>
    </form>
  </div>
</header>

<!-- Stats row -->
<div class="stats-row">
  <div class="stat"><div class="stat-val">{{ total }}</div><div class="stat-lbl">Total incidents</div></div>
  <div class="stat"><div class="stat-val">{{ qh_violations }}</div><div class="stat-lbl">Quiet hours violations</div></div>
  <div class="stat"><div class="stat-val">{{ qh_pct }}%</div><div class="stat-lbl">During quiet hours</div></div>
  <div class="stat"><div class="stat-val">{{ by_type|length }}</div><div class="stat-lbl">Event types</div></div>
</div>

<div style="display:flex;gap:1.5rem;flex-wrap:wrap;margin-bottom:1.5rem">
  <!-- Incident type breakdown -->
  <div class="card" style="flex:1;min-width:260px">
    <div class="card-title">Incident breakdown by type</div>
    {% for et, cnt in by_type.items() %}
    <div class="type-row">
      <span>{{ et.replace('_',' ') }}</span>
      <strong>{{ cnt }}</strong>
    </div>
    {% else %}
    <div class="type-row" style="color:#475569">No incidents</div>
    {% endfor %}
  </div>

  <!-- Hour-of-day heatmap -->
  <div class="card" style="flex:2;min-width:300px">
    <div class="card-title">Incidents by hour of day</div>
    <div class="heatmap">
      {% set max_h = (hour_counts | max) if hour_counts else 1 %}
      {% set max_h = max_h if max_h > 0 else 1 %}
      <div class="heatmap-row">
        <div class="heatmap-lbl"></div>
        <div class="heatmap-bars">
          {% for h in range(24) %}
          {% set intensity = (hour_counts[h] / max_h) %}
          <div class="heatmap-bar"
               title="{{ hour_counts[h] }} incident(s) at {{ '%02d:00' % h }}"
               style="background: rgba(14,165,233,{{ 0.1 + intensity * 0.9 }});"></div>
          {% endfor %}
        </div>
      </div>
      <div class="heatmap-row">
        <div class="heatmap-lbl"></div>
        <div class="heatmap-bars" style="gap:2px">
          {% for h in [0,3,6,9,12,15,18,21] %}
          <div style="flex:3;font-size:.65rem;color:#475569;text-align:left">{{ '%02d'%h }}</div>
          {% endfor %}
        </div>
      </div>
    </div>
  </div>

  <!-- Day-of-week heatmap -->
  <div class="card" style="flex:1;min-width:220px">
    <div class="card-title">Incidents by day of week</div>
    <div class="heatmap">
      {% set max_d = (dow_counts | max) if dow_counts else 1 %}
      {% set max_d = max_d if max_d > 0 else 1 %}
      {% set dow_labels = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'] %}
      {% for d in range(7) %}
      {% set intensity = (dow_counts[d] / max_d) %}
      <div class="heatmap-row">
        <div class="heatmap-lbl">{{ dow_labels[d] }}</div>
        <div class="heatmap-bars">
          <div class="heatmap-bar"
               title="{{ dow_counts[d] }} incident(s) on {{ dow_labels[d] }}"
               style="background:rgba(14,165,233,{{ 0.1 + intensity * 0.9 }});max-width:none;"></div>
        </div>
        <div style="font-size:.72rem;color:#64748b;padding-left:.4rem;width:1.5rem">{{ dow_counts[d] }}</div>
      </div>
      {% endfor %}
    </div>
  </div>
</div>

<!-- Incident timeline -->
<div class="card">
  <div class="card-title">Incident timeline ({{ total }} total)</div>
  {% if incidents %}
  <table>
    <thead>
      <tr>
        <th>Started</th>
        <th>Type</th>
        <th>Duration</th>
        <th>Peak dB</th>
        <th>Severity</th>
        <th>Quiet hours</th>
        <th>Detections</th>
        <th>Status</th>
      </tr>
    </thead>
    <tbody>
    {% for inc in incidents %}
      <tr>
        <td>{{ inc.started_at[:16] }}</td>
        <td>{{ inc.event_type.replace('_',' ') }}</td>
        <td>{{ '%.0fs' % inc.duration_seconds }}</td>
        <td>{{ '%.1f' % inc.peak_db }}</td>
        <td>
          {% set sev = inc.severity_score %}
          {% if sev >= 0.7 %}
            <span class="severity-dot" style="background:#ef4444"></span>{{ '%.0f%%' % (sev*100) }}
          {% elif sev >= 0.4 %}
            <span class="severity-dot" style="background:#f59e0b"></span>{{ '%.0f%%' % (sev*100) }}
          {% else %}
            <span class="severity-dot" style="background:#22c55e"></span>{{ '%.0f%%' % (sev*100) }}
          {% endif %}
        </td>
        <td>{{ '✓' if inc.quiet_hours_violation else '' }}</td>
        <td>{{ inc.detection_count }}</td>
        <td>
          <select class="status-sel" data-id="{{ inc.incident_id }}" onchange="updateStatus(this)">
            <option value="pending" {% if inc.review_status == 'pending' %}selected{% endif %}>Pending</option>
            <option value="reviewed" {% if inc.review_status == 'reviewed' %}selected{% endif %}>Reviewed</option>
            <option value="dismissed" {% if inc.review_status == 'dismissed' %}selected{% endif %}>Dismissed</option>
          </select>
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}
  <div style="padding:1.5rem;color:#475569;font-size:.9rem">No incidents found for this case.</div>
  {% endif %}
</div>

<script>
function updateStatus(sel) {
  const id = sel.dataset.id;
  const status = sel.value;
  fetch('/api/incidents/' + id, {
    method: 'PATCH',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({review_status: status})
  }).then(r => {
    if (!r.ok) { alert('Failed to update status'); sel.value = sel.dataset.prev; }
    else { sel.dataset.prev = status; }
  });
}
document.querySelectorAll('.status-sel').forEach(s => s.dataset.prev = s.value);
</script>
</body>
</html>"""


PORTAL_SETTINGS_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sentinel — Portal Settings</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#0b1120;color:#e2e8f0;font-family:system-ui,sans-serif;padding:1.5rem}
  header{display:flex;align-items:center;justify-content:space-between;margin-bottom:1.5rem}
  h1{font-size:1.2rem;font-weight:700}
  .badge{display:inline-block;background:#0ea5e920;color:#38bdf8;border-radius:4px;padding:.15rem .5rem;font-size:.75rem;font-weight:600;margin-right:.5rem}
  a.btn-sm{background:#1e2d45;color:#94a3b8;border-radius:6px;padding:.4rem .8rem;font-size:.8rem;text-decoration:none}
  a.btn-sm:hover{background:#263548;color:#e2e8f0}
  .card{background:#151d2e;border:1px solid #1e2d45;border-radius:10px;padding:1.5rem;max-width:420px}
  label{display:block;font-size:.8rem;color:#94a3b8;margin-bottom:.35rem}
  input{width:100%;background:#0b1120;border:1px solid #1e2d45;border-radius:6px;color:#e2e8f0;padding:.6rem .75rem;font-size:.9rem;outline:none;margin-bottom:1rem}
  input:focus{border-color:#38bdf8}
  .btn{background:#0ea5e9;color:#fff;border:none;border-radius:6px;padding:.6rem 1.25rem;font-size:.9rem;font-weight:600;cursor:pointer}
  .btn:hover{background:#0284c7}
  .msg{background:#14532d;border:1px solid #4ade80;border-radius:6px;padding:.6rem .75rem;font-size:.85rem;color:#4ade80;margin-bottom:1rem}
  .hint{font-size:.75rem;color:#475569;margin-top:-.75rem;margin-bottom:1rem}
</style>
</head>
<body>
<header>
  <div>
    <span class="badge">OFFICER PORTAL</span>
    <h1>Settings</h1>
  </div>
  <a class="btn-sm" href="{{ url_for('portal_cases') }}">← Cases</a>
</header>
<div class="card">
  {% if message %}<div class="msg">{{ message }}</div>{% endif %}
  <form method="post">
    <label>Officer username</label>
    <input type="text" name="username" value="{{ username }}" autocomplete="username">
    <label>New password</label>
    <input type="password" name="password" placeholder="Leave blank to keep current" autocomplete="new-password">
    <div class="hint">Default password is "sentinel" if none has been set.</div>
    <button class="btn" type="submit">Save</button>
  </form>
</div>
</body>
</html>"""
