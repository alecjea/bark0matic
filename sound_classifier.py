"""Sound classification using YAMNet TFLite model."""
import csv
import urllib.request
import numpy as np
import librosa
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

YAMNET_MODEL_URL = "https://storage.googleapis.com/download.tensorflow.org/models/tflite/task_library/audio_classification/android/lite-model_yamnet_classification_tflite_1.tflite"
YAMNET_CLASS_MAP_URL = "https://raw.githubusercontent.com/tensorflow/models/master/research/audioset/yamnet/yamnet_class_map.csv"
YAMNET_SAMPLE_RATE = 16000
MODEL_DIR = Path(__file__).parent / "models"


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

    def _load_model(self):
        """Download and load YAMNet TFLite model with retry and validation."""
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        model_path = MODEL_DIR / "yamnet.tflite"
        class_map_path = MODEL_DIR / "yamnet_class_map.csv"

        # Download model with retry and validation
        self._download_with_retry(
            YAMNET_MODEL_URL, model_path,
            "YAMNet TFLite model (~3MB)", min_size=2_000_000
        )
        self._download_with_retry(
            YAMNET_CLASS_MAP_URL, class_map_path,
            "YAMNet class map", min_size=1000
        )

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
            # Model file might be corrupt — delete it so next run re-downloads
            if model_path.exists():
                model_path.unlink()
                print("[INFO] Removed corrupt model file — will re-download on next start")
            self.interpreter = None

    def _download_with_retry(self, url, dest, label, min_size=0, retries=3):
        """Download a file with retry logic and size validation."""
        if dest.exists() and dest.stat().st_size >= min_size:
            return  # Already have a valid file

        # Remove partial/corrupt file
        if dest.exists():
            print(f"[INFO] Removing invalid {dest.name} ({dest.stat().st_size} bytes)")
            dest.unlink()

        for attempt in range(1, retries + 1):
            try:
                print(f"[INFO] Downloading {label} (attempt {attempt}/{retries})...")
                tmp_path = dest.with_suffix(".tmp")
                urllib.request.urlretrieve(url, tmp_path)

                # Validate file size
                if tmp_path.stat().st_size < min_size:
                    print(f"[WARN] Download too small ({tmp_path.stat().st_size} bytes), retrying...")
                    tmp_path.unlink()
                    continue

                # Rename to final path (atomic on same filesystem)
                tmp_path.rename(dest)
                print(f"[INFO] Downloaded {label}")
                return

            except Exception as e:
                print(f"[WARN] Download failed (attempt {attempt}): {e}")
                # Clean up partial file
                tmp_path = dest.with_suffix(".tmp")
                if tmp_path.exists():
                    tmp_path.unlink()

        print(f"[ERROR] Failed to download {label} after {retries} attempts")
        print(f"[ERROR] URL: {url}")

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
                    waveform = librosa.resample(
                        waveform,
                        orig_sr=self.source_sample_rate,
                        target_sr=YAMNET_SAMPLE_RATE,
                    )

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
                return is_match, confidence, frequency

            except Exception as e:
                print(f"[ERROR] YAMNet inference failed: {e}")
                return False, 0.0, frequency

        return self._heuristic_classify(features)

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
