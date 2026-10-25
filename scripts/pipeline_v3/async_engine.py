"""
Pipeline v3.0 — Asynchronous Dual-Model Execution Engine & HTTP Session Pooling
"""

import os
import time
import queue
import threading
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from .qa_gate import query_crisperwhisper_qa
from .auk_repair import repair_and_verify_chunk
from .normalizer import inject_contextual_paralinguistics

def create_pooled_session() -> requests.Session:
    """Creates a persistent requests.Session with connection pooling and keep-alive."""
    session = requests.Session()
    adapter = HTTPAdapter(
        pool_connections=25,
        pool_maxsize=25,
        max_retries=Retry(
            total=3,
            backoff_factor=0.3,
            status_forcelist=[500, 502, 503, 504],
            raise_on_status=False
        )
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

def synthesize_thought_chunk_sync(
    session: requests.Session,
    server_url: str,
    asr_url: str,
    ref_audio_path: str,
    ref_text: str,
    text: str,
    chunk_id: str,
    temp_dir: str,
    qa_threshold: float = 0.93,
    profile_id: str | None = None,
    auk_url: str | None = "http://127.0.0.1:3950",
    initial_wav: bytes | None = None,
    initial_acc: float = 0.0,
    initial_asr: str = "",
    allow_auk: bool = True,
) -> tuple[str | None, float, str]:
    """
    Synthesizes a single thought chunk with cached chunk fast-path and monotonic quality repair loop.
    Supports persistent profile_id for zero-upload VRAM prompt caching on GB10 / Blackwell GPUs.
    When seeded with initial_wav from the pipelined producer, skips redundant steps=16 pass
    and guarantees retries never downgrade a high-scoring initial take.
    """
    wav_cache = os.path.join(temp_dir, f"{chunk_id}.wav")
    if os.path.exists(wav_cache) and os.path.getsize(wav_cache) > 1000:
        return wav_cache, 0.98, text

    if not text or not text.strip():
        return None, 1.0, ""

    best_wav = initial_wav
    best_acc = float(initial_acc) if initial_wav else 0.0
    best_asr = initial_asr if (initial_wav and initial_asr) else text

    if initial_wav is not None:
        # Producer already ran steps=16; only run higher-precision diffusion schedules
        if best_acc >= 0.90:
            configs = [{"g_scale": 2.2, "steps": 20}]
        else:
            configs = [
                {"g_scale": 2.2, "steps": 20},
                {"g_scale": 1.6, "steps": 24},
            ]
    else:
        configs = [
            {"g_scale": 1.8, "steps": 16},
            {"g_scale": 2.2, "steps": 20},
            {"g_scale": 1.6, "steps": 24},
        ]

    for attempt, cfg in enumerate(configs, start=1):
        try:
            # Use contextual paralinguistics on initial attempt only; fallback to clean text on retries
            use_paralinguistics = (attempt == 1 and initial_wav is None)
            synth_text, _ = inject_contextual_paralinguistics(text, enable_tags=use_paralinguistics)
            pos_temp = 3.0 if (len(text) < 80 or attempt > 1 or initial_wav is not None) else 5.0
            data = {
                "text": synth_text,
                "language": "en",
                "speed": 1.0,
                "effect_preset": "broadcast",
                "guidance_scale": cfg["g_scale"],
                "num_step": cfg["steps"],
                "position_temperature": pos_temp,
                "max_chunk_chars": 0,
                "denoise": True
            }
            if profile_id:
                data["profile_id"] = profile_id
                resp = session.post(f"{server_url}/generate", data=data, timeout=60)
            else:
                data["ref_text"] = ref_text
                with open(ref_audio_path, "rb") as f:
                    files = {"ref_audio": (os.path.basename(ref_audio_path), f, "audio/wav")}
                    resp = session.post(f"{server_url}/generate", data=data, files=files, timeout=60)

            if resp.status_code == 200:
                wav_bytes = resp.content
                acc, asr_text = query_crisperwhisper_qa(session, asr_url, wav_bytes, text)
                if acc > best_acc:
                    best_acc = float(acc)
                    best_wav = wav_bytes
                    best_asr = asr_text
                if acc >= qa_threshold:
                    break
            else:
                print(f"   ❌ [HTTP {resp.status_code}] API Error: {resp.text[:100]}")
        except Exception as e:
            print(f"   ❌ [NETWORK ERROR] Request failed: {e}")
        time.sleep(0.1)

    # Single-pass AuK surgical repair only if not already attempted and still below threshold
    if allow_auk and auk_url and best_wav and best_acc < qa_threshold:
        healed, healed_wav, healed_acc, healed_asr = repair_and_verify_chunk(
            session, auk_url, asr_url, best_wav, text, best_asr, best_acc, qa_threshold
        )
        if healed_acc > best_acc:
            best_acc = float(healed_acc)
            best_wav = healed_wav
            best_asr = healed_asr

    if best_wav:
        with open(wav_cache, 'wb') as f:
            f.write(best_wav)
        return wav_cache, best_acc, best_asr

    return None, 0.0, ""

def process_chapter_pipelined(
    session: requests.Session,
    server_url: str,
    asr_url: str,
    ref_audio_path: str,
    ref_text: str,
    thoughts_with_flags: list[tuple[str, bool]],
    raw_file_idx: int,
    temp_dir: str,
    qa_threshold: float = 0.93,
    profile_id: str | None = None,
    auk_url: str | None = "http://127.0.0.1:3950"
) -> tuple[list[str], list[dict], float]:
    """
    Processes all thought chunks in a chapter using async dual-model pipelining:
      - TTS Generation (Port 3900) executes continuously on the producer thread.
      - CrisperWhisper QA (Port 8090) validates chunks concurrently on the consumer thread.
      - AuK Surgical Repair (Port 3950) heals localized sub-threshold chunks in-place once.
    Returns (ordered_chunk_paths, qa_results, average_qa_score).
    """
    chunk_paths = [None] * len(thoughts_with_flags)
    qa_results = [None] * len(thoughts_with_flags)

    # Fast check for already cached chunks
    uncached_indices = []
    for idx, (t_text, _) in enumerate(thoughts_with_flags):
        cid = f"ch{raw_file_idx:03d}_p{idx:03d}"
        w_path = os.path.join(temp_dir, f"{cid}.wav")
        if os.path.exists(w_path) and os.path.getsize(w_path) > 1000:
            chunk_paths[idx] = w_path
            qa_results[idx] = {
                "chunk_id": cid,
                "text": t_text,
                "transcription": t_text,
                "accuracy": 0.98
            }
        else:
            uncached_indices.append(idx)

    if not uncached_indices:
        avg_acc = 98.0
        return chunk_paths, qa_results, avg_acc

    # Dual-Model Asynchronous Pipeline Queue (expanded to 8 to prevent GPU producer stalls)
    asr_queue = queue.Queue(maxsize=8)
    stop_signal = object()

    def asr_consumer():
        while True:
            item = asr_queue.get()
            if item is stop_signal:
                asr_queue.task_done()
                break
            idx, cid, t_text, wav_bytes = item
            # Validate via CrisperWhisper Large concurrently on Port 8090
            acc, asr_txt = query_crisperwhisper_qa(session, asr_url, wav_bytes, t_text)
            if acc >= qa_threshold:
                w_path = os.path.join(temp_dir, f"{cid}.wav")
                with open(w_path, 'wb') as f:
                    f.write(wav_bytes)
                chunk_paths[idx] = w_path
                qa_results[idx] = {
                    "chunk_id": cid,
                    "text": t_text,
                    "transcription": asr_txt,
                    "accuracy": acc
                }
            else:
                # Attempt single in-place AuK surgical healing on localized 1-2 word flaws
                healed = False
                cur_best_wav = wav_bytes
                cur_best_acc = acc
                cur_best_asr = asr_txt
                if auk_url:
                    healed, healed_wav, healed_acc, healed_asr = repair_and_verify_chunk(
                        session, auk_url, asr_url, wav_bytes, t_text, asr_txt, acc, qa_threshold
                    )
                    if healed_acc > cur_best_acc:
                        cur_best_wav = healed_wav
                        cur_best_acc = healed_acc
                        cur_best_asr = healed_asr
                    if healed:
                        w_path = os.path.join(temp_dir, f"{cid}.wav")
                        with open(w_path, 'wb') as f:
                            f.write(healed_wav)
                        chunk_paths[idx] = w_path
                        qa_results[idx] = {
                            "chunk_id": cid,
                            "text": t_text,
                            "transcription": healed_asr,
                            "accuracy": healed_acc
                        }

                if not healed:
                    # Seeded targeted retry loop (never discards cur_best_wav, never calls AuK a second time)
                    w_path, repair_acc, final_asr = synthesize_thought_chunk_sync(
                        session, server_url, asr_url, ref_audio_path, ref_text,
                        t_text, cid, temp_dir, qa_threshold=qa_threshold,
                        profile_id=profile_id, auk_url=auk_url,
                        initial_wav=cur_best_wav, initial_acc=cur_best_acc,
                        initial_asr=cur_best_asr, allow_auk=False
                    )
                    chunk_paths[idx] = w_path
                    qa_results[idx] = {
                        "chunk_id": cid,
                        "text": t_text,
                        "transcription": final_asr,
                        "accuracy": repair_acc
                    }
            asr_queue.task_done()

    consumer_thread = threading.Thread(target=asr_consumer, daemon=True)
    consumer_thread.start()

    # Producer: Generates TTS chunks exclusively on Port 3900
    for idx in uncached_indices:
        t_text, _ = thoughts_with_flags[idx]
        cid = f"ch{raw_file_idx:03d}_p{idx:03d}"
        
        if not t_text or not t_text.strip():
            chunk_paths[idx] = None
            qa_results[idx] = {
                "chunk_id": cid,
                "text": "",
                "transcription": "",
                "accuracy": 1.0
            }
            continue

        try:
            synth_text, _ = inject_contextual_paralinguistics(t_text, enable_tags=True)
            is_short = len(t_text) < 80
            data = {
                "text": synth_text,
                "language": "en",
                "speed": 1.0,
                "effect_preset": "broadcast",
                "guidance_scale": 2.0,
                "num_step": 24 if is_short else 16,
                "position_temperature": 3.0 if is_short else 5.0,
                "max_chunk_chars": 0,
                "denoise": True
            }
            if profile_id:
                data["profile_id"] = profile_id
                resp = session.post(f"{server_url}/generate", data=data, timeout=60)
            else:
                data["ref_text"] = ref_text
                with open(ref_audio_path, "rb") as f:
                    files = {"ref_audio": (os.path.basename(ref_audio_path), f, "audio/wav")}
                    resp = session.post(f"{server_url}/generate", data=data, files=files, timeout=60)

            if resp.status_code == 200:
                wav_bytes = resp.content
                # Stream immediately into ASR validation queue
                asr_queue.put((idx, cid, t_text, wav_bytes))
            else:
                w_path, acc, final_asr = synthesize_thought_chunk_sync(
                    session, server_url, asr_url, ref_audio_path, ref_text,
                    t_text, cid, temp_dir, qa_threshold=qa_threshold,
                    profile_id=profile_id, auk_url=auk_url
                )
                chunk_paths[idx] = w_path
                qa_results[idx] = {
                    "chunk_id": cid,
                    "text": t_text,
                    "transcription": final_asr,
                    "accuracy": acc
                }
        except Exception as e:
            w_path, acc, final_asr = synthesize_thought_chunk_sync(
                session, server_url, asr_url, ref_audio_path, ref_text,
                t_text, cid, temp_dir, qa_threshold=qa_threshold,
                profile_id=profile_id, auk_url=auk_url
            )
            chunk_paths[idx] = w_path
            qa_results[idx] = {
                "chunk_id": cid,
                "text": t_text,
                "transcription": final_asr,
                "accuracy": acc
            }

    # Signal consumer and wait for validation queue drain
    asr_queue.put(stop_signal)
    consumer_thread.join()

    # Enforce 100% thought-chunk synthesis completeness (never allow partial chapters on backend OOM/500)
    missing_chunks = [
        f"ch{raw_file_idx:03d}_p{idx:03d}"
        for idx, (t_text, _) in enumerate(thoughts_with_flags)
        if t_text and t_text.strip() and not chunk_paths[idx]
    ]
    if missing_chunks:
        raise RuntimeError(
            f"Chapter {raw_file_idx:03d} incomplete: {len(missing_chunks)} thought chunk(s) failed to synthesize "
            f"(first: {missing_chunks[0]}). Halting before encoding partial chapter."
        )

    # Calculate average accuracy
    valid_accs = [r["accuracy"] for r in qa_results if r and "accuracy" in r]
    avg_acc = (sum(valid_accs) / len(valid_accs) * 100.0) if valid_accs else 100.0
    return chunk_paths, qa_results, avg_acc

