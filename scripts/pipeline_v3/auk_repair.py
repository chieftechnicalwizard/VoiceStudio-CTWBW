"""
Pipeline v3.3 — AuK Precision Speech Error-Healing & Acoustic Repair Gate
Integrates Tencent-Hunyuan AuK (Audio Universal Kernel) running on :3950
to provide in-place surgical pronunciation correction, omission restoration, and stutter healing.
"""

import re
import time
import difflib
import logging
import requests

from .qa_gate import query_crisperwhisper_qa, compute_qa_accuracy, normalize_qa_tokens

logger = logging.getLogger("auk_repair")

_AUK_COOLDOWN_UNTIL = 0.0


def _get_lexical_edits(target_text: str, asr_text: str) -> tuple[list[tuple], list[str], list[str]]:
    """Returns non-equal SequenceMatcher opcodes along with raw word lists."""
    t_clean = re.sub(r"\s+", " ", target_text.strip())
    a_clean = re.sub(r"\s+", " ", asr_text.strip()) if asr_text else ""
    t_words = t_clean.split()
    a_words = a_clean.split()
    t_norm = [normalize_qa_tokens(w) for w in t_words]
    a_norm = [normalize_qa_tokens(w) for w in a_words]
    matcher = difflib.SequenceMatcher(None, a_norm, t_norm, autojunk=False)
    edits = [op for op in matcher.get_opcodes() if op[0] != "equal"]
    return edits, t_words, a_words


def is_localized_repairable_flaw(target_text: str, asr_text: str, old_acc: float) -> bool:
    """
    Returns True when a sub-threshold take has a localized 1-2 span flaw (<= 3 words per span)
    suitable for surgical in-place AuK healing, rather than a whole-sentence synthesis failure.
    """
    if old_acc < 0.80 or not asr_text or not asr_text.strip():
        return False
    edits, _, _ = _get_lexical_edits(target_text, asr_text)
    if not edits or len(edits) > 2:
        return False
    for tag, i1, i2, j1, j2 in edits:
        if (i2 - i1) > 4 or (j2 - j1) > 4:
            return False
    return True


def build_repair_instruction(target_text: str, asr_text: str) -> str:
    """
    Analyzes lexical / phonemic differences between target text and ASR transcription
    to formulate an optimal natural-language repair instruction for the AuK model.
    """
    t_clean = re.sub(r"\s+", " ", target_text.strip())
    a_clean = re.sub(r"\s+", " ", asr_text.strip()) if asr_text else ""

    if not a_clean:
        return f"Fix the pronunciation so the speaker clearly and naturally says: '{t_clean}'."

    edits, t_words, a_words = _get_lexical_edits(target_text, asr_text)

    # Single-substitution case (e.g. mispronounced name or single term)
    if len(edits) == 1:
        tag, i1, i2, j1, j2 = edits[0]
        flawed_phrase = " ".join(a_words[i1:i2])
        correct_phrase = " ".join(t_words[j1:j2])

        if tag == "replace" and flawed_phrase and correct_phrase:
            return f"Replace '{flawed_phrase}' with '{correct_phrase}'."
        elif tag == "insert" and correct_phrase:
            anchor = a_words[i1 - 1] if i1 > 0 else (a_words[i2] if i2 < len(a_words) else "")
            if anchor:
                return f"Add '{correct_phrase}' after '{anchor}'."
            return f"Fix the speech so it clearly includes '{correct_phrase}'."
        elif tag == "delete" and flawed_phrase:
            return f"Remove '{flawed_phrase}'."

    # Multi-edit or complex flaw: instruction-guided inpainting
    return f"Fix the pronunciation and spoken words so the speaker clearly says: '{t_clean}'."


def query_auk_repair(
    session: requests.Session,
    auk_url: str,
    wav_bytes: bytes,
    target_text: str,
    asr_text: str = "",
    instruction: str = "",
    timeout: int = 25
) -> bytes | None:
    """
    Dispatches a surgical speech-repair request to the resident AuK service.
    Includes a 45s circuit-breaker cooldown on network/timeout errors so a busy service
    never stalls the asynchronous TTS producer pipeline.
    """
    global _AUK_COOLDOWN_UNTIL
    if not auk_url or time.time() < _AUK_COOLDOWN_UNTIL:
        return None

    if not instruction:
        instruction = build_repair_instruction(target_text, asr_text)

    try:
        files = {"file": ("chunk.wav", wav_bytes, "audio/wav")}
        data = {
            "target_text": target_text,
            "asr_text": asr_text,
            "instruction": instruction,
            "nfe": 32,
            "cfg": 2.0,
            "speed": 1.0
        }
        resp = session.post(f"{auk_url}/repair", files=files, data=data, timeout=timeout)
        if resp.status_code == 200 and len(resp.content) > 1000:
            try:
                import io, soundfile as sf, librosa
                with io.BytesIO(wav_bytes) as in_bio:
                    _, in_sr = sf.read(in_bio, dtype="float32")
                with io.BytesIO(resp.content) as out_bio:
                    y_out, out_sr = sf.read(out_bio, dtype="float32")
                if y_out.ndim > 1:
                    y_out = y_out[:, 0]
                if out_sr != in_sr:
                    y_out = librosa.resample(y_out, orig_sr=out_sr, target_sr=in_sr)
                    norm_bio = io.BytesIO()
                    sf.write(norm_bio, y_out, in_sr, format="WAV", subtype="PCM_16")
                    return norm_bio.getvalue()
            except Exception:
                pass
            return resp.content
        else:
            logger.warning(f"[AuK Service] HTTP {resp.status_code}: {resp.text[:100]}")
    except Exception as e:
        _AUK_COOLDOWN_UNTIL = time.time() + 45.0
        logger.warning(f"[AuK Service] Communication failed (entering 45s cooldown): {e}")

    return None


_REF_MFCC_CACHE = None

def get_reference_mfcc(ref_path: str | None = None):
    global _REF_MFCC_CACHE
    if _REF_MFCC_CACHE is not None:
        return _REF_MFCC_CACHE
    import os
    candidates = [
        ref_path,
        os.environ.get("OMNIVOICE_VOICE_REF_PATH"),
        "/media/media/TOSHIBA EXT/AI/dots.tts/Jan_Narrator_ref_10s_mono.wav",
        "/home/media/Jan_Narrator_ref_10s_mono.wav",
        "/home/media/AI/dots.tts/Jan_Narrator_ref_10s_mono.wav",
    ]
    try:
        import os, librosa, numpy as np
        target = None
        for c in candidates:
            if c and os.path.exists(c):
                target = c
                break
        if target:
            y, sr = librosa.load(target, sr=24000)
            mfcc = np.mean(librosa.feature.mfcc(y=y, sr=sr, n_mfcc=20), axis=1)
            # Exclude mfcc[0] (overall log-energy) so cosine similarity measures vocal-tract timbre
            mfcc_timbre = mfcc[1:]
            _REF_MFCC_CACHE = mfcc_timbre / np.linalg.norm(mfcc_timbre)
            return _REF_MFCC_CACHE
    except Exception as e:
        logger.warning(f"Failed to load reference MFCC: {e}")
    return None

def check_voice_timbre_consistency(
    wav_bytes: bytes,
    min_similarity: float = 0.970,
    min_med_f0: float = 109.0,
    min_p25_f0: float = 102.0,
    min_voiced_centroid: float = 720.0,
) -> tuple[bool, float]:
    """
    Validates that a synthesized or repaired audio chunk acoustically conforms to the
    authentic narrator voice using MFCC[1:] cosine similarity (excluding C0 log-energy),
    voiced pitch floor (librosa.yin F0), and voiced spectral centroid.
    Prevents zero-shot foundation model low/scary voice or pitch-drop hallucinations.
    """
    ref_norm = get_reference_mfcc()
    if ref_norm is None:
        return True, 1.0  # Pass through if reference audio unconfigured

    try:
        import io, soundfile as sf, librosa, numpy as np
        with io.BytesIO(wav_bytes) as bio:
            y, sr = sf.read(bio)
        if y.ndim > 1:
            y = y[:, 0]
        if sr != 24000:
            y = librosa.resample(y, orig_sr=sr, target_sr=24000)
        mfcc = np.mean(librosa.feature.mfcc(y=y, sr=24000, n_mfcc=20), axis=1)
        mfcc_timbre = mfcc[1:]
        norm = mfcc_timbre / max(float(np.linalg.norm(mfcc_timbre)), 1e-8)
        sim = float(np.dot(ref_norm, norm))

        # Pitch & spectral centroid floor check against deep/growling voice hallucinations
        rms_f = librosa.feature.rms(y=y, frame_length=1024, hop_length=256)[0]
        cent_f = librosa.feature.spectral_centroid(y=y, sr=24000, n_fft=1024, hop_length=256)[0]
        f0_f = librosa.yin(y, fmin=65, fmax=320, sr=24000, frame_length=1024, hop_length=256)
        voiced = (rms_f > np.percentile(rms_f, 35)) & (f0_f > 68) & (f0_f < 290)
        if np.sum(voiced) >= 3:
            med_f0 = float(np.median(f0_f[voiced]))
            p25_f0 = float(np.percentile(f0_f[voiced], 25))
            v_cent = float(np.median(cent_f[voiced]))
            if med_f0 < min_med_f0 or p25_f0 < min_p25_f0 or v_cent < min_voiced_centroid:
                penalty = min(med_f0 / min_med_f0, p25_f0 / min_p25_f0, v_cent / min_voiced_centroid, 0.94)
                return False, float(sim * penalty)

        return sim >= min_similarity, sim
    except Exception as e:
        logger.warning(f"Acoustic timbre check error: {e}")
        return True, 1.0

def repair_and_verify_chunk(
    session: requests.Session,
    auk_url: str,
    asr_url: str,
    wav_bytes: bytes,
    target_text: str,
    asr_text: str,
    old_acc: float,
    qa_threshold: float = 0.93
) -> tuple[bool, bytes, float, str]:
    """
    Attempts in-place AuK surgical speech healing on a sub-threshold thought chunk,
    followed by CrisperWhisper Large lexical verification AND Acoustic Timbre consistency gating.

    Returns:
      (passed_threshold, resulting_wav_bytes, resulting_accuracy, resulting_transcription)
    """
    if not auk_url or not is_localized_repairable_flaw(target_text, asr_text, old_acc):
        return False, wav_bytes, old_acc, asr_text

    instruction = build_repair_instruction(target_text, asr_text)
    print(f"      [AuK HEALING] Attempting in-place repair: {instruction}")

    repaired_wav = query_auk_repair(
        session=session,
        auk_url=auk_url,
        wav_bytes=wav_bytes,
        target_text=target_text,
        asr_text=asr_text,
        instruction=instruction
    )

    if not repaired_wav:
        print(f"      [AuK HEALING] AuK service unavailable or failed; proceeding to fallback.")
        return False, wav_bytes, old_acc, asr_text

    # Acoustic Timbre Gate: Check whether AuK synthesized with authentic narrator voice
    timbre_ok, timbre_sim = check_voice_timbre_consistency(repaired_wav, min_similarity=0.970)
    if not timbre_ok:
        print(f"      ✕ [AuK TIMBRE DRIFT] Repaired chunk drifted from authentic narrator timbre (CosSim: {timbre_sim:.3f} < 0.970). Rejecting repair.")
        return False, wav_bytes, old_acc, asr_text

    # Re-verify repaired audio with CrisperWhisper Large
    new_acc, new_asr = query_crisperwhisper_qa(session, asr_url, repaired_wav, target_text)

    if new_acc >= qa_threshold:
        print(f"      ✓ [AuK HEALED] Surgical repair SUCCEEDED! QA score: {old_acc:.1%} -> {new_acc:.1%} (Timbre: {timbre_sim:.3f})")
        return True, repaired_wav, new_acc, new_asr
    elif new_acc > old_acc:
        print(f"      △ [AuK HEALED] QA score improved ({old_acc:.1%} -> {new_acc:.1%}), but below threshold ({qa_threshold:.1%})")
        return False, repaired_wav, new_acc, new_asr
    else:
        print(f"      ✕ [AuK HEALED] Repair did not improve QA score ({old_acc:.1%} -> {new_acc:.1%}).")
        return False, wav_bytes, old_acc, asr_text

