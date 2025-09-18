"""
This file contains the Predictor class, which is used to run predictions on the
Whisper model. It is based on the Predictor class from the original Whisper
repository, with some modifications to make it work with the RP platform.
"""

import gc
import threading
from concurrent.futures import (
    ThreadPoolExecutor,
)  # Still needed for transcribe potentially?
import numpy as np

from runpod.serverless.utils import rp_cuda
import stable_whisper

# Import torch for CUDA memory management
try:
    import torch

    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

AVAILABLE_MODELS = {
    "medium.en",
}


class Predictor:
    """A Predictor class for the Whisper model with lazy loading"""

    def __init__(self):
        """Initializes the predictor with no models loaded."""
        self.model = None
        self.model_lock = threading.Lock()  # Lock for thread-safe model access

    def setup(self):
        """Pre-load medium.en model to avoid loading delays and memory issues."""
        print("Loading medium.en model during setup...")

        # Clear CUDA cache before loading model to maximize available memory
        if rp_cuda.is_available():
            gc.collect()
            if TORCH_AVAILABLE:
                torch.cuda.empty_cache()
                print("Cleared CUDA cache before model loading")

        try:
            self.model = stable_whisper.load_faster_whisper(
                "medium.en",
                device="cuda" if rp_cuda.is_available() else "cpu",
                compute_type="float16" if rp_cuda.is_available() else "int8",
                # Optimize memory usage
                cpu_threads=4 if not rp_cuda.is_available() else 0,
            )
            print("medium.en model loaded successfully and cached.")
        except Exception as e:
            print(f"Error loading medium.en model during setup: {e}")
            # Try to clear memory and provide helpful error message
            if rp_cuda.is_available():
                gc.collect()
                if TORCH_AVAILABLE:
                    torch.cuda.empty_cache()
            raise RuntimeError(
                f"Failed to load medium.en model during setup: {e}"
            ) from e

    def predict(
        self,
        audio,
        model_name="base",
        transcription="plain_text",
        translate=False,
        translation="plain_text",  # Added in a previous PR
        language=None,
        temperature=0,
        best_of=5,
        beam_size=5,
        patience=1,
        length_penalty=None,
        suppress_tokens="-1",
        initial_prompt=None,
        condition_on_previous_text=True,
        temperature_increment_on_fallback=0.2,
        compression_ratio_threshold=2.4,
        logprob_threshold=-1.0,
        no_speech_threshold=0.6,
        enable_vad=False,
        vad_parameters=None,
        word_timestamps=False,
    ):
        """
        Run a single prediction on the model, loading/unloading models as needed.
        """
        if model_name not in AVAILABLE_MODELS:
            raise ValueError(
                f"Invalid model name: {model_name}. Available models are: {AVAILABLE_MODELS}"
            )

        # Use the pre-loaded model (always medium)
        with self.model_lock:
            if self.model is None:
                raise RuntimeError(
                    "Model not loaded. Ensure setup() was called successfully."
                )
            model = self.model
            print(f"Using cached model: {model_name}")

        # Model is now loaded and ready, proceed with prediction (outside the lock?)
        # Consider if transcribe is thread-safe or if it should also be within the lock
        # For now, keeping transcribe outside as it's CPU/GPU bound work

        if temperature_increment_on_fallback is not None:
            temperature = tuple(
                np.arange(temperature, 1.0 + 1e-6, temperature_increment_on_fallback)
            )
        else:
            temperature = [temperature]

        # Note: FasterWhisper's transcribe might release the GIL, potentially allowing
        # other threads to acquire the model_lock if transcribe is lengthy.
        # If issues arise, the lock might need to encompass the transcribe call too.
        result = model.transcribe(
            str(audio),
            language=language,
            task="transcribe",
            beam_size=beam_size,
            best_of=best_of,
            patience=patience,
            length_penalty=length_penalty,
            temperature=temperature,
            compression_ratio_threshold=compression_ratio_threshold,
            log_prob_threshold=logprob_threshold,
            no_speech_threshold=no_speech_threshold,
            condition_on_previous_text=condition_on_previous_text,
            initial_prompt=initial_prompt,
            prefix=None,
            suppress_blank=True,
            suppress_tokens=[-1],  # Might need conversion from string
            without_timestamps=False,
            max_initial_timestamp=1.0,
            word_timestamps=word_timestamps,
            vad_filter=enable_vad,
            vad_parameters=vad_parameters,
        )

        # Format transcription
        transcription_output = result.to_srt_vtt()

        results = {
            "transcription": transcription_output,
            "device": "cuda" if rp_cuda.is_available() else "cpu",
            "model": model_name,
        }

        return results


def serialize_segments(transcript):
    """
    Serialize the segments to be returned in the API response.
    """
    return [
        {
            "id": segment.id,
            "seek": segment.seek,
            "start": segment.start,
            "end": segment.end,
            "text": segment.text,
            "tokens": segment.tokens,
            "temperature": segment.temperature,
            "avg_logprob": segment.avg_logprob,
            "compression_ratio": segment.compression_ratio,
            "no_speech_prob": segment.no_speech_prob,
        }
        for segment in transcript
    ]
