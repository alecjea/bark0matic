"""Sound classification using YAMNet TFLite model."""
import csv
import hashlib
import numpy as np
from pathlib import Path

try:
    from ai_edge_litert import interpreter as tflite
    TFLITE_AVAILABLE = True
except ImportError:
    try:
        import tflite_runtime.interpreter as tflite
        TFLITE_AVAILABLE = True
    except ImportError:
        try:
            import tensorflow as tf
            tflite = tf.lite
            TFLITE_AVAILABLE = True
        except ImportError:
            TFLITE_AVAILABLE = False
            print("[WARN] No TFLite runtime available, falling back to heuristic")

from config import Config

YAMNET_SAMPLE_RATE = 16000
MODEL_DIR = Path(__file__).parent / "models"

# Pinned SHA-256 hashes — files must match exactly before being loaded
YAMNET_MODEL_SHA256     = "10c95ea3eb9a7bb4cb8bddf6feb023250381008177ac162ce169694d05c317de"
YAMNET_CLASS_MAP_SHA256 = "cdf24d193e196d9e95912a2667051ae203e92a2ba09449218ccb40ef787c6df2"


def _sha256_file(path: Path) -> str:
    """Return lowercase hex SHA-256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class SoundClassifier:
    """Classifies audio using YAMNet TFLite model against configurable target classes."""

    def __init__(self):
        self.threshold = Config.BARK_DETECTION_THRESHOLD
        self.source_sample_rate = Config.RPI_MICROPHONE_RATE
        self.target_indices = Config.SOUND_TYPE_INDICES
        self.interpreter = None

        if TFLITE_AVAILABLE:
            self._load_model()
        else:
            print("[WARN] Running without YAMNet — install ai-edge-litert")

    def _verify_file(self, path: Path, expected_sha256: str, label: str) -> bool:
        """Return True if file exists and matches expected SHA-256, else log and return False."""
        if not path.exists():
            print(f"[ERROR] {label} not found at {path}")
            print(f"[ERROR] Run install.sh to download model files")
            return False
        actual = _sha256_file(path)
        if actual.lower() != expected_sha256.lower():
            print(f"[ERROR] {label} hash mismatch!")
            print(f"[ERROR]   expected: {expected_sha256}")
            print(f"[ERROR]   actual:   {actual}")
            print(f"[ERROR] Delete {path} and re-run install.sh")
            return False
        return True

    def _load_model(self):
        """Verify and load YAMNet TFLite model from local files only."""
        model_path     = MODEL_DIR / "yamnet.tflite"
        class_map_path = MODEL_DIR / "yamnet_class_map.csv"

        if not self._verify_file(model_path, YAMNET_MODEL_SHA256, "YAMNet model"):
            print("[WARN] Falling back to heuristic classifier")
            return
        if not self._verify_file(class_map_path, YAMNET_CLASS_MAP_SHA256, "YAMNet class map"):
            print("[WARN] Falling back to heuristic classifier")
            return

        try:
            self.interpreter = tflite.Interpreter(model_path=str(model_path))
            self.interpreter.allocate_tensors()
            self._log_target_classes(class_map_path)
            print(
                f"[INFO] YAMNet loaded. Detecting: {Config.SOUND_TYPE_NAME} "
                f"(indices: {self.target_indices})"
            )
        except Exception as e:
            print(f"[ERROR] Failed to load YAMNet: {e}")
            self.interpreter = None

    def _log_target_classes(self, class_map_path):
        """Log the target class names from the class map."""
        try:
            with open(class_map_path, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if int(row["index"]) in self.target_indices:
                        print(f"[INFO] Target class: [{row['index']}] {row['display_name']}")
        except Exception:
            pass

    def reload_config(self):
        """Reload threshold and indices from config (for live updates via web UI)."""
        self.threshold = Config.BARK_DETECTION_THRESHOLD
        self.target_indices = Config.SOUND_TYPE_INDICES

    def classify(self, features, raw_audio=None):
        """
        Classify audio against target sound classes.

        Args:
            features: Audio features dict from AudioProcessor
            raw_audio: Raw audio samples for YAMNet

        Returns:
            tuple: (is_match, confidence, frequency)
        """
        if features is None:
            return False, 0.0, 0.0

        frequency = features.get("spec_centroid_mean", 0.0)

        if self.interpreter is not None and raw_audio is not None:
            try:
                waveform = raw_audio.astype(np.float32) / 32768.0
                if self.source_sample_rate != YAMNET_SAMPLE_RATE:
                    # Fast numpy resample instead of slow librosa
                    ratio = YAMNET_SAMPLE_RATE / self.source_sample_rate
                    new_len = int(len(waveform) * ratio)
                    waveform = np.interp(
                        np.linspace(0, len(waveform) - 1, new_len),
                        np.arange(len(waveform)),
                        waveform
                    ).astype(np.float32)

                input_details = self.interpreter.get_input_details()
                output_details = self.interpreter.get_output_details()

                self.interpreter.resize_tensor_input(
                    input_details[0]["index"], [len(waveform)]
                )
                self.interpreter.allocate_tensors()
                self.interpreter.set_tensor(input_details[0]["index"], waveform)
                self.interpreter.invoke()

                scores = self.interpreter.get_tensor(output_details[0]["index"])
                mean_scores = np.mean(scores, axis=0)

                confidence = (
                    float(max(mean_scores[i] for i in self.target_indices))
                    if self.target_indices
                    else 0.0
                )
                is_match = confidence >= self.threshold
                return is_match, confidence, frequency, mean_scores.tolist()

            except Exception as e:
                print(f"[ERROR] YAMNet inference failed: {e}")
                return False, 0.0, frequency, []

        is_match, confidence, frequency = self._heuristic_classify(features)
        return is_match, confidence, frequency, []

    def _heuristic_classify(self, features):
        """Fallback heuristic classifier when YAMNet is unavailable."""
        scores = []
        decibels = features.get("decibels", -np.inf)
        energy_threshold = Config.BARK_DETECTION_ENERGY_THRESHOLD

        energy_score = (
            min(1.0, (decibels - energy_threshold) / 20.0)
            if decibels > energy_threshold
            else 0.0
        )
        scores.append(energy_score * 0.3)

        spec_centroid = features.get("spec_centroid_mean", 0)
        min_freq = Config.BARK_DETECTION_MIN_FREQUENCY
        max_freq = Config.BARK_DETECTION_MAX_FREQUENCY
        if min_freq <= spec_centroid <= max_freq:
            freq_score = 1.0
        elif spec_centroid > max_freq:
            freq_score = max(0.0, 1.0 - (spec_centroid - max_freq) / 2000)
        else:
            freq_score = max(0.0, 1.0 - (min_freq - spec_centroid) / 500)
        scores.append(freq_score * 0.4)

        zcr = features.get("zcr_mean", 0)
        zcr_score = 1.0 - abs(zcr - 0.25) / 0.25 if 0.05 < zcr < 0.5 else 0.0
        scores.append(zcr_score * 0.2)

        spec_rolloff = features.get("spec_rolloff_mean", 0)
        rolloff_score = min(1.0, spec_rolloff / 3000) if spec_rolloff > 1000 else 0.0
        scores.append(rolloff_score * 0.1)

        confidence = sum(scores)
        return confidence >= self.threshold, float(confidence), float(spec_centroid)

    def get_explanation(self, features, is_match, confidence):
        """Human-readable explanation of classification result."""
        decibels = features.get("decibels", -np.inf) if features else -np.inf
        spec_centroid = features.get("spec_centroid_mean", 0) if features else 0
        engine = "YAMNet" if self.interpreter is not None else "heuristic"
        result = "DETECTED" if is_match else "—"
        return (
            f"{result} [{engine}] (confidence: {confidence:.2f}) | "
            f"dB: {decibels:.1f} | Freq: {spec_centroid:.0f}Hz"
        )
