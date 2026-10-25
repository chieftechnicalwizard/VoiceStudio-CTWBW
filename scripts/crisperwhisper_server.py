#!/usr/bin/env python3
"""
CrisperWhisper 2.0 Large — Production FastAPI Microservice Server (:8090)
Provides low-latency (<1.2s) verbatim & intended speech recognition with word timestamps
for OmniVoice Studio (`CrisperWhisperBackend` / `OMNIVOICE_ASR_BACKEND=crisper-whisper`)
and Pipeline v3 audiobook QA verification.
"""

import os
import time
import platform
import tempfile
from typing import Optional, Dict

import torch
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from pydantic import BaseModel
from crisperwhisper import CrisperWhisperModel

app = FastAPI(
    title="CrisperWhisper 2.0 Production API Server",
    description="High-performance verbatim & intended speech recognition API with word timestamps and dual-mode decoding.",
    version="2.0.0",
)

# Determine optimal backend (transformers on AArch64/GB10, auto/ctranslate2 on x86_64)
if platform.machine().lower() in ("aarch64", "arm64"):
    DEFAULT_BACKEND = "transformers"
else:
    try:
        import ctranslate2  # noqa: F401
        DEFAULT_BACKEND = "auto"
    except ImportError:
        DEFAULT_BACKEND = "transformers"

loaded_models: Dict[str, CrisperWhisperModel] = {}


def get_or_load_model(model_name: str = "large", compute_type: str = "float16") -> CrisperWhisperModel:
    cache_key = f"{model_name}_{compute_type}_{DEFAULT_BACKEND}"
    if cache_key not in loaded_models:
        target_path = os.environ.get("CRISPERWHISPER_MODEL_PATH", model_name)
        local_dir = os.path.join(os.path.dirname(__file__), "models", f"CrisperWhisper2.0_{model_name}")
        if os.path.exists(local_dir):
            target_path = local_dir

        print(f"Loading CrisperWhisper model: {target_path} (backend={DEFAULT_BACKEND}, compute_type={compute_type})...")
        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            model = CrisperWhisperModel(
                target_path,
                backend=DEFAULT_BACKEND,
                compute_type=compute_type,
                device="cuda" if torch.cuda.is_available() else "cpu",
            )
        except Exception as e:
            print(f"Failed to initialize on GPU ({e}); falling back to CPU execution...")
            model = CrisperWhisperModel(
                target_path,
                backend=DEFAULT_BACKEND,
                compute_type="float32",
                device="cpu",
            )

        loaded_models[cache_key] = model
    return loaded_models[cache_key]


class TranscribeRequestParams(BaseModel):
    model_name: Optional[str] = "large"
    language: Optional[str] = "en"
    mode: Optional[str] = "verbatim"
    word_timestamps: Optional[bool] = False
    speculative_decoding: Optional[bool] = False
    compute_type: Optional[str] = "float16"


@app.get("/health")
def health_check():
    gpu_available = torch.cuda.is_available()
    gpu_name = torch.cuda.get_device_name(0) if gpu_available else "N/A"
    vram_alloc = torch.cuda.memory_allocated(0) / (1024**2) if gpu_available else 0
    vram_res = torch.cuda.memory_reserved(0) / (1024**2) if gpu_available else 0
    return {
        "status": "online",
        "gpu_available": gpu_available,
        "gpu_name": gpu_name,
        "vram_allocated_mb": round(vram_alloc, 2),
        "vram_reserved_mb": round(vram_res, 2),
        "loaded_models": list(loaded_models.keys()),
    }


@app.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    model_name: str = Form("large"),
    language: str = Form("en"),
    mode: str = Form("verbatim"),
    word_timestamps: bool = Form(False),
    speculative_decoding: bool = Form(False),
    compute_type: str = Form("float16"),
):
    tmp_path = None
    try:
        model = get_or_load_model(model_name=model_name, compute_type=compute_type)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            tmp.write(await file.read())
            tmp_path = tmp.name

        start_time = time.time()
        try:
            result = model.transcribe(
                tmp_path,
                language=language,
                mode=mode,
                word_timestamps=word_timestamps,
                speculative_decoding=speculative_decoding,
            )
        except Exception as oom_err:
            if "out of memory" in str(oom_err).lower():
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                local_dir = os.path.join(os.path.dirname(__file__), "models", f"CrisperWhisper2.0_{model_name}")
                target_path = local_dir if os.path.exists(local_dir) else model_name
                cpu_model = CrisperWhisperModel(target_path, backend=DEFAULT_BACKEND, compute_type="float32", device="cpu")
                result = cpu_model.transcribe(
                    tmp_path,
                    language=language,
                    mode=mode,
                    word_timestamps=word_timestamps,
                    speculative_decoding=False,
                )
            else:
                raise oom_err
        duration = round(time.time() - start_time, 4)

        words = []
        if word_timestamps and getattr(result, "words", None) is not None:
            words = [{"word": w.word, "start": round(w.start, 3), "end": round(w.end, 3)} for w in result.words]

        return {
            "text": result.text,
            "language": language,
            "mode": mode,
            "execution_time_seconds": duration,
            "words": words,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8090))
    uvicorn.run(app, host="0.0.0.0", port=port)
