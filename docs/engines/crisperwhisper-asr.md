# CrisperWhisper 2.0 Large — Resident HTTP ASR Engine

## Overview

OmniVoice Studio includes a first-class HTTP ASR backend (**`CrisperWhisperBackend`**, engine ID: `crisper-whisper`) in [`backend/services/asr_backend.py`](../../backend/services/asr_backend.py) paired with the standalone FastAPI microservice in [`scripts/crisperwhisper_server.py`](../../scripts/crisperwhisper_server.py).

By running **Nyra Health `CrisperWhisper 2.0 Large`** as an independent resident microservice on port `8090`, OmniVoice Studio and the Pipeline v3 Audiobook QA Engine share a single warm VRAM allocation (`~3.1–7.1 GB` with `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`) with `<1.2s` transcription latency per clip.

---

## 1. Architecture & Integration

| Component | Path | Responsibility |
| :--- | :--- | :--- |
| **OmniVoice ASR Adapter** | `backend/services/asr_backend.py` (`CrisperWhisperBackend`) | Registered in `_REGISTRY["crisper-whisper"]` and prioritized #1 in `_auto_detect()` when `/health` responds on `OMNIVOICE_CRISPERWHISPER_URL`. Handles voice-reference auto-transcription, dictation, and dubbing alignment. |
| **FastAPI Microservice** | `scripts/crisperwhisper_server.py` | Serves `GET /health` and `POST /transcribe` (`mode="verbatim"` for audiobook disfluency/stutter detection; `mode="intended"` for clean voice-reference transcription). Automatically selects `transformers` on AArch64 Grace Blackwell (`sm_121`) and `ctranslate2`/`auto` on x86_64 Blackwell (`sm_120`). |
| **Pipeline v3 QA Gate** | `scripts/pipeline_v3/qa_gate.py` | Calls `POST /transcribe` on every synthesized thought chunk, scoring word/character alignment (`compute_qa_accuracy`) and rejecting syllable stutters or fillers (`has_asr_stutter_or_filler`). |
| **Regression Suite** | `tests/test_crisperwhisper_backend.py` | Verifies `_REGISTRY` registration, `_auto_detect()` priority, GPU compatibility, and `/transcribe` payload formatting. |

---

## 2. Running the Microservice

```bash
export PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True"
export PORT=8090
python3 scripts/crisperwhisper_server.py
```

Configure OmniVoice Studio to use the microservice:

```bash
export OMNIVOICE_ASR_BACKEND="crisper-whisper"
export OMNIVOICE_CRISPERWHISPER_URL="http://127.0.0.1:8090/transcribe"
```
