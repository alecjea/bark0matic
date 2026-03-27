"""JSON-based configuration for barkomatic."""
import json
from pathlib import Path
from zoneinfo import ZoneInfo


CONFIG_PATH = Path(__file__).parent / "config.json"


class Config:
    """Configuration loaded from config.json with save support."""

    # Sound detection target
    SOUND_TYPE_NAME = "Dog bark"
    SOUND_TYPE_INDICES = [69, 70, 75]
    LOCAL_TIMEZONE = "Australia/Melbourne"

    # Audio
    RPI_MICROPHONE_DEVICE = "auto"
    RPI_MICROPHONE_RATE = 16000
    RPI_MICROPHONE_CHANNELS = 1
    RPI_MICROPHONE_DTYPE = "int16"

    # Detection thresholds
    BARK_DETECTION_CHUNK_SIZE = 2.0
    BARK_DETECTION_THRESHOLD = 0.3
    BARK_DETECTION_MIN_FREQUENCY = 50
    BARK_DETECTION_MAX_FREQUENCY = 5000
    BARK_DETECTION_MIN_DURATION = 0.5
    BARK_DETECTION_ENERGY_THRESHOLD = -60

    # Dog size classification
    DOG_SIZE_FREQUENCY_THRESHOLD = 2000  # Hz — below = large dog, above = small dog

    # Logging
    LOG_DB_PATH = str(Path(__file__).parent / "detections.db")
    BACKUP_LOG_FILE = "/tmp/barkomatic_backup.json"

    # Web
    WEB_PORT = 8080

    @classmethod
    def load(cls):
        """Load configuration from config.json."""
        if not CONFIG_PATH.exists():
            print("[CONFIG] No config.json found, using defaults")
            return

        try:
            with open(CONFIG_PATH, "r") as f:
                data = json.load(f)

            for key, value in data.items():
                key_upper = key.upper()
                if key_upper == "LOG_FILE_PATH":
                    if isinstance(value, str) and value.endswith(".csv"):
                        cls.LOG_DB_PATH = str(Path(value).with_suffix(".db"))
                    else:
                        cls.LOG_DB_PATH = value
                elif hasattr(cls, key_upper):
                    setattr(cls, key_upper, value)

            print("[CONFIG] Configuration loaded from config.json")
        except Exception as e:
            print(f"[CONFIG] Error loading config.json: {e}, using defaults")

    @classmethod
    def save(cls):
        """Save current configuration back to config.json."""
        data = {
            "sound_type_name": cls.SOUND_TYPE_NAME,
            "sound_type_indices": cls.SOUND_TYPE_INDICES,
            "local_timezone": cls.LOCAL_TIMEZONE,
            "rpi_microphone_device": cls.RPI_MICROPHONE_DEVICE,
            "rpi_microphone_rate": cls.RPI_MICROPHONE_RATE,
            "rpi_microphone_channels": cls.RPI_MICROPHONE_CHANNELS,
            "rpi_microphone_dtype": cls.RPI_MICROPHONE_DTYPE,
            "bark_detection_chunk_size": cls.BARK_DETECTION_CHUNK_SIZE,
            "bark_detection_threshold": cls.BARK_DETECTION_THRESHOLD,
            "bark_detection_min_frequency": cls.BARK_DETECTION_MIN_FREQUENCY,
            "bark_detection_max_frequency": cls.BARK_DETECTION_MAX_FREQUENCY,
            "bark_detection_min_duration": cls.BARK_DETECTION_MIN_DURATION,
            "bark_detection_energy_threshold": cls.BARK_DETECTION_ENERGY_THRESHOLD,
            "dog_size_frequency_threshold": cls.DOG_SIZE_FREQUENCY_THRESHOLD,
            "log_db_path": cls.LOG_DB_PATH,
            "web_port": cls.WEB_PORT,
        }
        try:
            with open(CONFIG_PATH, "w") as f:
                json.dump(data, f, indent=2)
            print("[CONFIG] Configuration saved")
        except Exception as e:
            print(f"[CONFIG] Error saving config.json: {e}")

    @classmethod
    def get_timezone(cls):
        """Get ZoneInfo for the configured timezone."""
        try:
            return ZoneInfo(cls.LOCAL_TIMEZONE)
        except Exception:
            return ZoneInfo("UTC")

    @classmethod
    def to_dict(cls):
        """Return current config as a dict for API responses."""
        return {
            "sound_type_name": cls.SOUND_TYPE_NAME,
            "sound_type_indices": cls.SOUND_TYPE_INDICES,
            "local_timezone": cls.LOCAL_TIMEZONE,
            "microphone_device": cls.RPI_MICROPHONE_DEVICE,
            "threshold": cls.BARK_DETECTION_THRESHOLD,
            "min_frequency": cls.BARK_DETECTION_MIN_FREQUENCY,
            "max_frequency": cls.BARK_DETECTION_MAX_FREQUENCY,
            "energy_threshold": cls.BARK_DETECTION_ENERGY_THRESHOLD,
            "chunk_size": cls.BARK_DETECTION_CHUNK_SIZE,
            "dog_size_frequency_threshold": cls.DOG_SIZE_FREQUENCY_THRESHOLD,
            "web_port": cls.WEB_PORT,
        }


# Auto-load on import
Config.load()
