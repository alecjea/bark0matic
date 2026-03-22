#!/usr/bin/env python3
"""Barkomatic — entry point. Runs sound detector + web UI."""
import signal
import sys
from config import Config
from sound_detector import SoundDetector
from web_server import create_app


def main():
    detector = SoundDetector()
    app = create_app(detector)

    # Start detection in background thread
    detector.start()

    # Graceful shutdown
    def shutdown(signum, frame):
        print("\n[INFO] Shutting down...")
        detector.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Run Flask (blocks)
    print(f"[WEB] Dashboard at http://0.0.0.0:{Config.WEB_PORT}")
    app.run(host="0.0.0.0", port=Config.WEB_PORT, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
