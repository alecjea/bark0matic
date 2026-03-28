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
    """Classifies audio using YAMNet TFLite model."""

    SPEECH_LABEL_KEYWORDS = (
        "speech",
        "conversation",
        "narration",
        "monologue",
        "babbling",
        "whispering",
        "whisper",
        "child speech",
        "synthetic speech",
    )

    def __init__(self):
        self.threshold = Config.BARK_DETECTION_THRESHOLD
        self.source_sample_rate = Config.RPI_MICROPHONE_RATE
        self.interpreter = None
        self.class_labels = {}
        self.available_sounds = []
        self.excluded_sound_indices = set()

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
            self._load_class_map(class_map_path)
            print(
                f"[INFO] YAMNet loaded. Monitoring all sounds above "
                f"threshold {self.threshold:.2f}"
            )
        except Exception as e:
            print(f"[ERROR] Failed to load YAMNet: {e}")
            self.interpreter = None

    def _load_class_map(self, class_map_path):
        """Load all available YAMNet classes and derive excluded speech classes."""
        try:
            with open(class_map_path, newline="") as f:
                reader = csv.DictReader(f)
                self.class_labels = {}
                self.available_sounds = []
                self.excluded_sound_indices = set()
                for row in reader:
                    index = int(row["index"])
                    name = row["display_name"]
                    self.class_labels[index] = name
                    self.available_sounds.append({"index": index, "name": name})
                    if self._is_human_speech_label(name):
                        self.excluded_sound_indices.add(index)

            print(f"[INFO] Loaded {len(self.available_sounds)} YAMNet sound classes")
            if self.excluded_sound_indices:
                print(f"[INFO] Excluding {len(self.excluded_sound_indices)} human speech classes from logging")
        except Exception as e:
            print(f"[WARN] Failed to load class map: {e}")
            self.class_labels = {}
            self.available_sounds = []
            self.excluded_sound_indices = {0}

    def _is_human_speech_label(self, name):
        """Return True when a YAMNet class label represents human speech."""
        name_lower = name.lower()
        return any(keyword in name_lower for keyword in self.SPEECH_LABEL_KEYWORDS)

    def get_available_sounds(self):
        """Return all non-speech YAMNet sounds for UI selection."""
        return [
            sound for sound in self.available_sounds
            if sound["index"] not in self.excluded_sound_indices
        ]

    def reload_config(self):
        """Reload threshold from config (for live updates via web UI)."""
        self.threshold = Config.BARK_DETECTION_THRESHOLD

    def classify_all(self, features, raw_audio=None):
        """
        Classify audio against all YAMNet sound classes.

        Args:
            features: Audio features dict from AudioProcessor
            raw_audio: Raw audio samples for YAMNet

        Returns:
            tuple: (matches, frequency, all_scores)
        """
        if features is None:
            return [], 0.0, []

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
                matches = []
                for index, score in enumerate(mean_scores):
                    confidence = float(score)
                    if confidence < self.threshold:
                        continue
                    if index in self.excluded_sound_indices:
                        continue
                    matches.append({
                        "index": index,
                        "name": self.class_labels.get(index, f"Class {index}"),
                        "confidence": confidence,
                    })

                matches.sort(key=lambda item: item["confidence"], reverse=True)
                return matches, frequency, mean_scores.tolist()

            except Exception as e:
                print(f"[ERROR] YAMNet inference failed: {e}")
                return [], frequency, []

        is_match, _confidence, frequency = self._heuristic_classify(features)
        if is_match:
            print("[WARN] Heuristic mode cannot safely classify all sounds; skipping log event")
        return [], frequency, []

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

    def get_explanation(self, features, matches):
        """Human-readable explanation of classification result."""
        decibels = features.get("decibels", -np.inf) if features else -np.inf
        spec_centroid = features.get("spec_centroid_mean", 0) if features else 0
        engine = "YAMNet" if self.interpreter is not None else "heuristic"
        if matches:
            top = ", ".join(
                f"{item['name']} ({item['confidence']:.2f})"
                for item in matches[:3]
            )
            result = f"DETECTED {top}"
        else:
            result = "—"
        return (
            f"{result} [{engine}] | "
            f"dB: {decibels:.1f} | Freq: {spec_centroid:.0f}Hz"
        )
