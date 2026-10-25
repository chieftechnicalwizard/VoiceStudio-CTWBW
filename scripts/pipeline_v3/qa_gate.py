"""
Pipeline v3.3 — Precision Token & Phonetic QA Gate (CrisperWhisper 2.0 Large)
"""

import re
import difflib
import requests

# Canonical lexical map for honorifics, US/UK spellings, and common ASR orthographic variants
_CANONICAL_TOKEN_MAP = {
    "mr": "mister",
    "mrs": "misses",
    "ms": "miss",
    "dr": "doctor",
    "prof": "professor",
    "sgt": "sergeant",
    "lt": "lieutenant",
    "capt": "captain",
    "gen": "general",
    "col": "colonel",
    "st": "saint",
    "mt": "mount",
    "ok": "okay",
    "okey": "okay",
    "til": "until",
    "till": "until",
    "grey": "gray",
    "theatre": "theater",
    "centre": "center",
    "colour": "color",
    "colours": "colors",
    "coloured": "colored",
    "favour": "favor",
    "favours": "favors",
    "favoured": "favored",
    "favourite": "favorite",
    "honour": "honor",
    "honours": "honors",
    "honoured": "honored",
    "humour": "humor",
    "labour": "labor",
    "neighbour": "neighbor",
    "neighbours": "neighbors",
    "rumour": "rumor",
    "rumours": "rumors",
    "savour": "savor",
    "savoured": "savored",
    "realise": "realize",
    "realised": "realized",
    "recognise": "recognize",
    "recognised": "recognized",
    "apologise": "apologize",
    "apologised": "apologized",
    "cancelled": "canceled",
    "travelling": "traveling",
    "travelled": "traveled",
    "traveller": "traveler",
    "labelled": "labeled",
    "judgement": "judgment",
    "axe": "ax",
    "whisky": "whiskey",
    "blonde": "blond",
    "gillian": "jillian",
    "stewart": "stuart",
    "steven": "stephen",
    "sean": "shawn",
    "shaun": "shawn",
    "kaitlin": "caitlin",
    "katherine": "catherine",
    "kathryn": "catherine",
    "caine": "kane",
    "macgregor": "mcgregor",
    "macgregors": "mcgregors",
    "numb": "num",
    "em": "them",
    "cause": "because",
    "cuz": "because",
    "maam": "madam",
}

_SAFE_OPEN_COMPOUNDS = {
    ("in", "to"): "into",
    ("on", "to"): "onto",
    ("any", "more"): "anymore",
    ("any", "way"): "anyway",
    ("may", "be"): "maybe",
    ("some", "day"): "someday",
    ("some", "one"): "someone",
    ("any", "one"): "anyone",
    ("every", "one"): "everyone",
    ("every", "day"): "everyday",
    ("can", "not"): "cannot",
    ("all", "right"): "alright",
    ("per", "cent"): "percent",
    ("do", "not"): "dont",
    ("does", "not"): "doesnt",
    ("did", "not"): "didnt",
    ("will", "not"): "wont",
    ("would", "not"): "wouldnt",
    ("could", "not"): "couldnt",
    ("should", "not"): "shouldnt",
    ("would", "have"): "wouldve",
    ("could", "have"): "couldve",
    ("should", "have"): "shouldve",
    ("is", "not"): "isnt",
    ("are", "not"): "arent",
    ("was", "not"): "wasnt",
    ("were", "not"): "werent",
    ("have", "not"): "havent",
    ("has", "not"): "hasnt",
    ("had", "not"): "hadnt",
    ("i", "am"): "im",
    ("you", "are"): "youre",
    ("we", "are"): "were",
    ("they", "are"): "theyre",
    ("it", "is"): "its",
    ("that", "is"): "thats",
    ("what", "is"): "whats",
    ("there", "is"): "theres",
}


def _phonetic_key(word: str) -> str:
    """
    Lightweight phonetic skeleton for proper-noun and homophone comparison.
    Maps identical-sounding orthographic variants (e.g. Keeley/Keely, Kerry/Carrie,
    Stuart/Stewart, Yung/Young, MacKade/McKade, Kendesa/Kandesa) to the same key.
    """
    w = word.lower()
    if len(w) < 3:
        return w
    w = re.sub(r"^mac", "mc", w)
    w = re.sub(r"ph", "f", w)
    w = re.sub(r"ght", "t", w)
    w = re.sub(r"ck", "k", w)
    w = re.sub(r"c(?=[eiy])", "s", w)
    w = re.sub(r"c", "k", w)
    w = re.sub(r"^g(?=[eiy])", "j", w)
    w = re.sub(r"(?:ee|ea|ie|ey|ei)", "y", w)
    w = re.sub(r"(?:ew|ue|oo)", "u", w)
    w = re.sub(r"ou", "u", w)
    w = re.sub(r"([a-z])\1+", r"\1", w)
    if len(w) > 4 and w.endswith("e"):
        w = w[:-1]
    w_head, w_tail = w[0], re.sub(r"[aeiouy]", "", w[1:])
    return w_head + w_tail


def _are_phonetic_homophones(w1: str, w2: str) -> bool:
    """Returns True if two tokens are near-identical phonetic homophones (not split/dropped words)."""
    if w1 == w2:
        return True
    if len(w1) < 4 or len(w2) < 4:
        return False
    # Handle minor trailing participle/possessive 'd'/'s' drops on long rare words (e.g. cologned/cologne)
    if len(w1) >= 6 and (w1.rstrip("ds") == w2.rstrip("ds")):
        return True
    if _phonetic_key(w1) == _phonetic_key(w2):
        sim = difflib.SequenceMatcher(None, w1, w2, autojunk=False).ratio()
        if sim >= 0.70:
            return True
    return False


def _align_compounds_and_homophones(t_words: list[str], a_words: list[str]) -> tuple[list[str], list[str]]:
    """
    1. Aligns open vs closed compound words when both roots are >= 4 chars (e.g., 'over warm' <-> 'overwarm')
       or in _SAFE_OPEN_COMPOUNDS, while strictly preserving single-letter dropcap ('t he') and short prefix
       split penalties ('re turn', 'un able').
    2. Canonicalizes phonetic proper-noun homophones so ASR spelling choices aren't penalized.
    """
    t_set = set(t_words)
    a_set = set(a_words)

    def _merge_open_compounds(words: list[str], ref_set: set[str]) -> list[str]:
        out = []
        i = 0
        n = len(words)
        while i < n:
            if i + 1 < n:
                w1, w2 = words[i], words[i + 1]
                joined = _SAFE_OPEN_COMPOUNDS.get((w1, w2), w1 + w2)
                # Merge only if joined exists in reference AND both parts are >= 4 chars (or safe open compound)
                if joined in ref_set and ((len(w1) >= 4 and len(w2) >= 4) or (w1, w2) in _SAFE_OPEN_COMPOUNDS):
                    out.append(joined)
                    i += 2
                    continue
            out.append(words[i])
            i += 1
        return out

    a_merged = _merge_open_compounds(a_words, t_set)
    t_merged = _merge_open_compounds(t_words, set(a_merged))

    # Align phonetic homophones against target tokens
    a_aligned = list(a_merged)
    for idx, aw in enumerate(a_aligned):
        if aw in t_set:
            continue
        # Check nearby window in t_merged for phonetic match
        lo = max(0, idx - 3)
        hi = min(len(t_merged), idx + 4)
        for tw in t_merged[lo:hi]:
            if _are_phonetic_homophones(tw, aw):
                a_aligned[idx] = tw
                break

    return t_merged, a_aligned


_PARALINGUISTIC_QA_STRIP_RE = re.compile(
    r"\[(?:laughter|sigh|breath|pause(?:\s+\d+(?:\.\d+)?\s*(?:ms|s))?|"
    r"confirmation-en|question-en|question-ah|question-oh|question-ei|question-yi|"
    r"surprise-ah|surprise-oh|surprise-wa|surprise-yo|dissatisfaction-hnn)\]",
    re.IGNORECASE,
)


def normalize_qa_tokens(text: str) -> str:
    """Strips paralinguistic/pause tags, punctuation, standardizes whitespace, and canonicalizes honorifics/US-UK spellings."""
    text = _PARALINGUISTIC_QA_STRIP_RE.sub(" ", text)
    text = re.sub(r"\b([a-zA-Z])\.([a-zA-Z])\b", r"\1 \2", text)
    text = re.sub(r"[-_–—]", " ", text)
    text = re.sub(r"[^\w\s]", "", text.lower())
    raw_tokens = text.split()
    norm_tokens = [_CANONICAL_TOKEN_MAP.get(tok, tok) for tok in raw_tokens]
    return " ".join(norm_tokens)


def compute_qa_accuracy(target_text: str, asr_text: str) -> float:
    """
    Computes precision QA accuracy comparing target text and ASR transcription.
    Eliminates false-negative penalties for punctuation, US/UK spellings, honorifics,
    open/closed compounds, and proper-noun homophones, while enforcing strict word-level
    alignment to catch split-word and dropcap glitches.
    """
    t_clean = normalize_qa_tokens(target_text)
    a_clean = normalize_qa_tokens(asr_text)
    if not t_clean:
        return 0.0
    if not a_clean:
        return 0.0

    t_words_raw = t_clean.split()
    a_words_raw = a_clean.split()
    if not t_words_raw and not a_words_raw:
        return 1.0

    t_words, a_words = _align_compounds_and_homophones(t_words_raw, a_words_raw)
    t_aligned_str = " ".join(t_words)
    a_aligned_str = " ".join(a_words)

    # NOTE: autojunk=False is ESSENTIAL! Python difflib default autojunk=True triggers
    # quadratic heuristics that discard common characters/substrings on longer text (>200 chars),
    # falsely penalizing valid matching clauses and dropping QA accuracy from 99% to 88%.
    char_ratio = difflib.SequenceMatcher(None, t_aligned_str, a_aligned_str, autojunk=False).ratio()
    word_ratio = difflib.SequenceMatcher(None, t_words, a_words, autojunk=False).ratio()

    # Short thought protection (<= 3 words): calculate word overlap ratio
    if len(t_words) <= 3:
        matching_words = sum(1 for w in t_words if w in a_words)
        overlap_ratio = matching_words / max(len(t_words), 1)
        base_score = max(char_ratio, word_ratio, overlap_ratio)
    else:
        # Balanced composite (40% char, 60% word): prevents single-word drops or split mutations
        # from falsely passing behind high character similarity ratios (>98%).
        base_score = 0.40 * char_ratio + 0.60 * word_ratio

    return round(base_score, 4)


def query_crisperwhisper_qa(session: requests.Session, asr_url: str, wav_bytes: bytes, target_text: str) -> tuple[float, str]:
    """Queries CrisperWhisper 2.0 Large service with 3 retries; never silently passes on ASR failure."""
    if not asr_url:
        return 0.0, "ASR_URL_MISSING"

    import time
    for attempt in range(3):
        try:
            files = {'file': ('chunk.wav', wav_bytes, 'audio/wav')}
            resp = session.post(f"{asr_url}/transcribe", files=files, timeout=25)
            if resp.status_code == 200:
                res = resp.json()
                asr_text = res.get('text', '').strip()
                acc = compute_qa_accuracy(target_text, asr_text)
                return float(acc), asr_text
        except Exception:
            pass
        time.sleep(0.8 * (attempt + 1))
    return 0.0, "ASR_UNAVAILABLE"


