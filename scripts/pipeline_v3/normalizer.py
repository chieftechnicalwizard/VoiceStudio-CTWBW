"""
Pipeline v3.0 — Phonetic Normalizer & Text Sanitization Engine
"""

import re
import html
import unicodedata
from html import unescape
from html.parser import HTMLParser
from num2words import num2words

class PreflightHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.skip_tags = {'script', 'style', 'nav', 'header', 'footer', 'head', 'title'}
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.skip_tags:
            self.skip_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in self.skip_tags and self.skip_depth > 0:
            self.skip_depth -= 1

    def handle_data(self, data):
        if self.skip_depth == 0:
            self.text_parts.append(data)

    def get_text(self):
        return "".join(self.text_parts)


def mend_hyphenated_linebreaks(text: str) -> str:
    """Mends words split across lines with hyphens or spaces and separates accidentally fused compound words."""
    text = re.sub(r'(\b[a-zA-Z]{2,})-\s*\n\s*([a-zA-Z]{2,}\b)', r'\1\2', text)
    text = re.sub(r'\b([a-zA-Z]{2,})-\s+([a-zA-Z]{2,})\b', r'\1\2', text)
    # Separate words accidentally fused with pronouns/adverbs e.g. 'beensomeone' -> 'been someone', 'dreamedsomething' -> 'dreamed something'
    def split_fused(m):
        prefix = m.group(1)
        suffix = m.group(2)
        if prefix.lower() in ('some', 'any', 'every', 'no'):
            return m.group(0)
        return f"{prefix} {suffix}"
    text = re.sub(r'\b([a-zA-Z]{3,})(someone|something|somebody|somewhere|anyone|anything|anybody|anywhere|everywhere|everything|everyone)\b', split_fused, text, flags=re.IGNORECASE)
    return text


ACRONYM_WHITELIST = {'OPA', 'CIA', 'FBI', 'UN', 'MCRN', 'DNA', 'RNA', 'CPU', 'AI', 'NYPD', 'US', 'USA', 'UK'}


def mend_dropcap_and_inline_splits(text: str) -> str:
    """
    Robust drop cap, contraction, syllable break, and small-caps lead-in normalizer.
    Prevents BPE subword fragmentation and acoustic model affricate distortions.
    Preserves dialogue sentence capitalization and legitimate standalone words.
    """
    # 0. Heal UTF-8 / Windows-1252 double-encoded mojibake sequences before dash/quote normalization
    text = text.replace('â€”', ' — ').replace('â€“', ' – ').replace('â€¦', '...')
    text = text.replace('â€™', "'").replace('â€˜', "'").replace('â€œ', '"').replace('â€\x9d', '"')
    text = text.replace('â€"', ' — ').replace('â€', ' — ')

    # 1. Contractions FIRST: heal spaces before/after apostrophes: "I' M" -> "I'm", "They 're" -> "They're", "didn 't" -> "didn't"
    def heal_contraction(m):
        base = m.group(1)
        suffix = m.group(2)
        if base.isupper() and len(base) == 1:
            return f"{base}'{suffix.lower()}"
        elif base.isupper() and suffix.isupper():
            return f"{base.capitalize()}'{suffix.lower()}"
        return f"{base}'{suffix.lower()}"
    text = re.sub(r"\b([a-zA-Z]+)\s*['’]\s*(s|t|m|d|v|re|ll|ve)\b", heal_contraction, text, flags=re.IGNORECASE)

    # 1b. Smallcaps boundary fusion: "WENTby" -> "WENT by", "TObusiness" -> "TO business"
    # Matches all-caps lead/stem (>= 2 chars) abutting lowercase word (>= 2 chars) from unspaced tag closing
    smallcaps_whitelist = {'IDed', 'IDing', 'ODed', 'ODing', 'OKed', 'OKing'}
    def heal_smallcaps_fusion(m):
        full = m.group(0)
        if full in smallcaps_whitelist:
            return full
        return f"{m.group(1)} {m.group(2)}"
    text = re.sub(r"\b([A-Z]{2,})([a-z]{2,})\b", heal_smallcaps_fusion, text)

    # 1c. Unspaced contraction/possessive fused with following word across inline tags:
    # e.g. "you'reable" -> "you're able", "didn'thave" -> "didn't have", "WASN'TSURE" -> "WASN'T SURE", "MAC'SSTUDIO" -> "MAC'S STUDIO"
    text = re.sub(
        r"\b(you|we|they|I|he|she|it|who|what|where|when|there|that|isn|aren|wasn|weren|don|doesn|didn|won|wouldn|can|couldn|shouldn|haven|hasn|hadn)'(re|ve|ll|m|d|s|t)(able|less|sure|have|know|been|got|going|want|need|think|make|take|come|here|there|about|after|again|always|already|never|still|just|even|only|also|expected)\b",
        r"\1'\2 \3",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\b([A-Z]{2,}'(?:S|T|RE|VE|LL|D|M))(STUDIO|MACAROONS|OFFICE|HOUSE|ROOM|VOICE|EYES|HAND|HANDS|HEAD|FACE|HEART|LIFE|MIND|NAME|PLACE|SIDE|TIME|WORK|WORLD|EXPECTED|SURE|KNOW|HAVE|WANT|NEED|GOING|BEEN)\b",
        r"\1 \2",
        text,
    )
    # Fix unspaced sci-fi "'link" (commlink) fused to preceding modifier: "your'link" -> "your link"
    text = re.sub(r"\b(your|my|his|her|their|our|the|a|an|this|that|personal|desk|wrist|wall|pocket|unregistered|encrypted|private)'(link|links)\b", r"\1 \2", text, flags=re.IGNORECASE)

    # 1d. Unspaced article/preposition/pronoun before Capitalized word: "theRacing" -> "the Racing"
    text = re.sub(
        r"\b(the|and|for|with|from|into|onto|over|under|after|before|about|around|through|between|without|within|his|her|their|our|your|that|this|was|were|had|have|has|said|when|where|while|what|who)([A-Z][a-z]{2,})\b",
        r"\1 \2",
        text,
    )

    # 2. Syllable splits across dropcaps/formatting: "MU sic" -> "Music", "PUT ting" -> "Putting"
    # Matches uppercase stem followed by syllable suffix or doubled consonant + suffix
    def heal_syllable(m):
        w1 = m.group(1)
        w2 = m.group(2)
        # Exclude legitimate standalone English words
        if w1.lower() in {"be", "to", "is", "was", "are", "were", "much", "not", "so", "no", "we", "he", "do", "it", "in", "on", "at", "as", "by"}:
            return m.group(0)
        return f"{w1.capitalize()}{w2.lower()}"
    syllable_pat = r"\b([A-Z]{2,4})\s+([a-z]?(?:ing|ed|ly|tion|tions|ment|ments|sic|ance|ence|able|ible|ness|less|ful))\b"
    text = re.sub(syllable_pat, heal_syllable, text)

    # 3. Standard Dropcap healing (B-Z, precision A / I)
    def heal_caps(m):
        prefix = m.group(1)
        c1 = m.group(2)
        rest = m.group(3)
        return f"{prefix}{c1}{rest.lower()}"

    def heal_lower(m):
        prefix = m.group(1)
        return f"{prefix}{m.group(2)}{m.group(3)}"

    # Match start of line/thought, after sentence-ending punctuation, or opening quote
    quote_prefix = r'(^|(?<=[\n\r])|(?<=[.!?]\s)|(?<!\w)[«\"“\'‘\(\[\{]{1,2}\s*)'

    # B-Z dropcaps
    text = re.sub(quote_prefix + r'([B-HJ-Z])\s+([A-Z]{1,}\b)', heal_caps, text)
    text = re.sub(quote_prefix + r'([B-HJ-Z])\s+([a-zA-Z]{1,}\b)', heal_lower, text)

    # Precision A / I dropcaps
    ai_rest_caps = r'(?:FTER|BOUT|NOTHER|ND|LL|LMOST|LREADY|LTHOUGH|GAIN|CROSS|ROUND|MONG|CCORDING|CTUALLY|FFIRMATIVE|LEX\b|RNOLD\b|SH\b|DMISSION|NSWER|UGUST\b|PRIL\b|UTUMN\b|LWAYS\b|WAY\b|T\b|N\b|S\b)'
    ai_rest_lower = r'(?:fter|bout|nother|nd|ll|lmost|lready|lthough|gain|cross|round|mong|ccording|ctually|ffirmative|lex\b|rnold\b|sh\b|dmission|nswer|ugust\b|pril\b|utumn\b|lways\b|t\b|n\b|s\b)'

    text = re.sub(quote_prefix + r'(A)\s+(' + ai_rest_caps + r')\b', heal_caps, text)
    text = re.sub(quote_prefix + r'(A)\s+(' + ai_rest_lower + r')\b', heal_lower, text)

    i_rest_caps = r'(?:F\b|N\b|T\b|NTO\b|NSTEAD\b|NSIDE\b|NCOMING)'
    i_rest_lower = r'(?:f\b|n\b|t\b|nto\b|nstead\b|nside\b|ncoming)'

    text = re.sub(quote_prefix + r'(I)\s+(' + i_rest_caps + r')\b', heal_caps, text)
    text = re.sub(quote_prefix + r'(I)\s+(' + i_rest_lower + r')\b', heal_lower, text)

    # 3b. Mid-line all-caps drop-caps in headings/titles (e.g. "Chapter O NE", "Ever A FTER", "Winter R OSE", "The S Orcerer's D AUGHTER", "...w ith")
    text = re.sub(r'\b([B-HJ-Z])\s+([A-Z]{2,})\b', lambda m: f"{m.group(1)}{m.group(2).lower()}", text)
    text = re.sub(r'\bA\s+(FTER|UGUST|LWAYS|GAINST|ROUND|MONG)\b', lambda m: f"A{m.group(1).lower()}", text)
    text = re.sub(r'\b([B-HJ-Z])\s+([A-Z][a-z]{2,})\b', lambda m: f"{m.group(1)}{m.group(2).lower()}" if m.group(1) + m.group(2).lower() in {"Sorcerer", "Daughter", "Chapter", "Prologue"} else m.group(0), text)
    text = re.sub(r'(\.\.\.\s*)([a-z])\s+([a-z]{2,})\b', r'\1\2\3', text)
    text = re.sub(r'\bMc\s+([A-Z][a-z]+)\b', r'Mc\1', text)
    text = re.sub(r'\bMac\s+(Namara|Namaras|Drubber|Drnbber|Dougal|Donald|Gregor|Kenzie|Pherson|Millan|Leod)\b', lambda m: 'Mac' + m.group(1).replace('Drnbber', 'Drubber'), text)

    # 4. Smallcaps / All-Caps Lead-ins at beginning of paragraphs or thoughts
    # e.g. "Grace's FEET WERE NUMB all the way" -> "Grace's feet were numb all the way"
    def heal_lead_in(m):
        full = m.group(0)
        words = full.split()
        converted = []
        for i, w in enumerate(words):
            if w in ACRONYM_WHITELIST:
                converted.append(w)
            elif i == 0:
                converted.append(w.capitalize())
            else:
                converted.append(w.lower())
        return ' '.join(converted) + ' '

    text = re.sub(r'^(?:[«\"“\'‘]{0,2})([A-Z\'’a-z]{2,}(?:\s+[A-Z\'’]{2,}){1,5})\s+(?=[a-z])', heal_lead_in, text)

    # 5. ALL-CAPS Heading or Sentence Normalization (ONLY if text is genuinely all uppercase letters)
    words = text.split()
    alpha_words = [re.sub(r"^[^\w]+|[^\w]+$", "", w) for w in words]
    alpha_words = [w for w in alpha_words if any(c.isalpha() for c in w)]
    def is_word_allcaps(w):
        clean = re.sub(r"['’][a-z]+$", "", w)  # strip contraction suffix like 'm, 're
        return clean.isupper()

    if len(alpha_words) >= 2 and all(is_word_allcaps(w) for w in alpha_words):
        converted = []
        for w in words:
            clean_w = re.sub(r"^[^\w]+|[^\w]+$", "", w)
            clean_base = re.sub(r"['’][a-z]+$", "", clean_w)
            if clean_base in ACRONYM_WHITELIST:
                converted.append(w)
            else:
                lead = re.match(r"^[^\w]+", w)
                trail = re.search(r"[^\w]+$", w)
                lead_str = lead.group(0) if lead else ""
                trail_str = trail.group(0) if trail else ""
                core = w[len(lead_str):len(w)-len(trail_str)] if trail else w[len(lead_str):]
                if "'" in core or "’" in core:
                    parts = re.split(r"(['’])", core)
                    converted_core = parts[0].capitalize() + "".join(parts[1:]).lower()
                else:
                    converted_core = core.capitalize()
                converted.append(f"{lead_str}{converted_core}{trail_str}")
        text = ' '.join(converted)

    # 6. Universal affricate bug prevention (dots.tts BPE 'ringing' -> 'ring-ing')
    text = re.sub(r"\b(R|r)inging\b", r"\1ing-ing", text)
    text = re.sub(r"\bRINGING\b", r"Ring-ing", text)
    text = re.sub(r"\b(R|r)ingings\b", r"\1ing-ings", text)

    return text


EXPANSE_PHONETIC_REPLACEMENTS = [
    # Spaceships (Fluid unhyphenated phonetics: prevents DiT acoustic metric pauses)
    (r"\bDonnager('s)?\b", r"Doniger\1"),
    (r"\bDONNAGER\b", r"Doniger"),
    (r"\bRoss-ee-nahn-tay('s)?\b", r"Rocinante\1"),
    (r"\bROSS-EE-NAHN-TAY\b", r"Rocinante"),
    (r"\bRoh-see('s)?\b", r"Rossi\1"),
    (r"\bROH-SEE\b", r"Rossi"),
    (r"\bRoci('s)?\b", r"Rossi\1"),
    (r"\bROCI\b", r"Rossi"),
    (r"\bNaw-voo('s)?\b", r"Nauvoo\1"),
    (r"\bNAW-VOO\b", r"Nauvoo"),
    (r"\bRay-zur-bak('s)?\b", r"Razorback\1"),
    (r"\bRAY-ZUR-BAK\b", r"Razorback"),

    # Major Characters
    (r"\bAh-vah-sah-rah-lah('s)?\b", r"Avasarala\1"),
    (r"\bAH-VAH-SAH-RAH-LAH\b", r"Avasarala"),
    (r"\bKriss-chin('s)?\b", r"Chrisjen\1"),
    (r"\bKRISS-CHIN\b", r"Chrisjen"),
    (r"\bKah-mahl('s)?\b", r"Kamal\1"),
    (r"\bKAH-MAHL\b", r"Kamal"),
    (r"\bEe-nah-ross('s|')?\b", r"Inaross\1"),
    (r"\bEE-NAH-ROSS\b", r"Inaross"),
    (r"\bInaros('s|')?\b", r"Inaross\1"),
    (r"\bINAROS\b", r"Inaross"),
    (r"\bKah-mee-nah('s)?\b", r"Camina\1"),
    (r"\bKAH-MEE-NAH\b", r"Camina"),
    (r"\bNah-gah-tah('s)?\b", r"Nagata\1"),
    (r"\bNAH-GAH-TAH\b", r"Nagata"),
    (r"\bJoh-see-fuss('s)?\b", r"Josephus\1"),
    (r"\bJOH-SEE-FUSS\b", r"Josephus"),
    (r"\bKlayz\b", r"Klayz"),
    (r"\bKLAYZ\b", r"Klayz"),

    # Factions, Planets, & Terms (Natural English tokenization)
    (r"\bBell-ters\b", r"Belters"),
    (r"\bBell-ter\b", r"Belter"),
    (r"\bBELL-TERS\b", r"Belters"),
    (r"\bBELL-TER\b", r"Belter"),
    (r"\bbell-ters\b", r"belters"),
    (r"\bbell-ter\b", r"belter"),

    # Lang Belta / Belter Creole Expressions
    (r"\bBell-tahs\b", r"Beltas"),
    (r"\bBell-tah\b", r"Belta"),
    (r"\bBELL-TAHS\b", r"Beltas"),
    (r"\bBELL-TAH\b", r"Belta"),
    (r"\bbell-tahs\b", r"beltas"),
    (r"\bbell-tah\b", r"belta"),
    (r"\bbeh-Raht-nah('s)?\b", r"Beratna\1"),
    (r"\bBEH-RAHT-NAH\b", r"Beratna"),
    (r"\bSay-sah('s)?\b", r"Sesa\1"),
    (r"\bSAY-SAH\b", r"Sesa"),
    (r"\bKoh-pah-kee-stahn\b", r"Kopakistan"),
    (r"\bKOH-PAH-KEE-STAHN\b", r"Kopakistan"),
    (r"\bEen-yah-low-dah\b", r"Inyalowda"),
    (r"\bEEN-YAH-LOW-DAH\b", r"Inyalowda"),
    (r"\bWel-wah-lah('s)?\b", r"Welwala\1"),
    (r"\bWEL-WAH-LAH\b", r"Welwala"),
    (r"\bOy-ay\b", r"Oye"),
    (r"\bOY-AY\b", r"Oye"),
    (r"\bMee\s+boh-roh\b", r"Mi boro"),
    (r"\bMEE\s+BOH-ROH\b", r"Mi boro"),
    (r"\bYah-meng\b", r"Yameng"),
    (r"\bYAH-MENG\b", r"Yameng"),

    # Planetary Systems & Alien Technology (Remove hyphenation hazards)
    (r"\bLuh-koh-nee-uns\b", r"Laconians"),
    (r"\bLuh-koh-nee-un\b", r"Laconian"),
    (r"\bLuh-koh-nee-uh('s)?\b", r"Laconia\1"),
    (r"\bLUH-KOH-NEE-UH\b", r"Laconia"),
    (r"\bLuh-koh-nee\b", r"Laconia"),
    (r"\bproh-toh-moll-uh-kyools\b", r"protomolecules"),
    (r"\bproh-toh-moll-uh-kyool\b", r"protomolecule"),
    (r"\bProh-toh-moll-uh-kyools\b", r"Protomolecules"),
    (r"\bProh-toh-moll-uh-kyool\b", r"Protomolecule"),
    (r"\bproh-toh-plaz-um\b", r"protoplasm"),
    (r"\bProh-toh-plaz-um\b", r"Protoplasm"),
    (r"\bEye-luss('s|')?\b", r"Ilus\1"),
    (r"\bEYE-LUSS\b", r"Ilus"),
    (r"\bGan-ee-meed('s)?\b", r"Ganymede\1"),
    (r"\bGAN-EE-MEED\b", r"Ganymede"),
]


def apply_expanse_phonetics(text: str) -> str:
    """Applies canonical Expanse Pronunciation Master Guide replacements for Spaceships, Characters, and Factions."""
    for pat, rep in EXPANSE_PHONETIC_REPLACEMENTS:
        text = re.sub(pat, rep, text)
    return text


RINGING_CEDARS_PHONETIC_REPLACEMENTS = [
    # Prevents dots.tts BPE tokenizer from emitting 'Ġringing' or 'ĠR', 'inging' (which aliases with cringing/singeing -> rinjing)
    # Splitting into 'Ring-ing' / 'ring-ing' produces ['Ring', '-ing'] / ['ring', '-ing'] with crisp velar nasal /ŋ/ and zero affricate glide.
    (r"\b(R|r)inging\b", r"\1ing-ing"),
    (r"\bRINGING\b", r"Ring-ing"),
    (r"\b(R|r)ingings\b", r"\1ing-ings"),
    (r"\bRINGINGS\b", r"Ring-ings"),
    # Fix split compound words and contractions detected in saga manifests
    (r"\b(G|g)rand\s+(F|f)ather\b", r"\1randfather"),
    (r"\bThey\s+['\u2019]re\b", r"They're"),
]


def apply_ringing_cedars_phonetics(text: str) -> str:
    """Applies canonical Ringing Cedars of Russia phonetic fixes to ensure correct pronunciation."""
    for pat, rep in RINGING_CEDARS_PHONETIC_REPLACEMENTS:
        text = re.sub(pat, rep, text)
    return text



_PROTECTED_BRACKET_TAG_RE = re.compile(
    r"\[(?:laughter|sigh|breath|pause(?:\s+\d+(?:\.\d+)?\s*(?:ms|s))?|"
    r"confirmation-en|question-en|question-ah|question-oh|question-ei|question-yi|"
    r"surprise-ah|surprise-oh|surprise-wa|surprise-yo|dissatisfaction-hnn)\]",
    re.IGNORECASE,
)


def normalize_numbers_and_currency(text: str) -> str:
    """Phonetically expands numerals, currency, dates, decimals, and Roman numerals while protecting paralinguistic tags."""
    saved_tags: list[str] = []
    def _stash_tag(m):
        idx = len(saved_tags)
        saved_tags.append(m.group(0))
        return f"__OVTAG_{idx}__"
    text = _PROTECTED_BRACKET_TAG_RE.sub(_stash_tag, text)

    # Currency: $X million/billion/trillion
    text = re.sub(r'\$(\d+(?:\.\d+)?)\s*(million|billion|trillion)\b', r'\1 \2 dollars', text, flags=re.IGNORECASE)

    # Currency: $X.YY
    def replace_dollar_cents(m):
        dollars = int(m.group(1))
        cents = int(m.group(2))
        d_words = num2words(dollars)
        c_words = num2words(cents)
        return f"{d_words} dollars and {c_words} cents"
    text = re.sub(r'\$(\d+)\.(\d{2})\b', replace_dollar_cents, text)

    # Currency: $X
    def replace_dollars(m):
        dollars = int(m.group(1))
        return f"{num2words(dollars)} dollars"
    text = re.sub(r'\$(\d+)\b', replace_dollars, text)

    # Roman numerals in headers and titles
    roman_map = {
        "I": "One", "II": "Two", "III": "Three", "IV": "Four", "V": "Five",
        "VI": "Six", "VII": "Seven", "VIII": "Eight", "IX": "Nine", "X": "Ten",
        "XI": "Eleven", "XII": "Twelve", "XIII": "Thirteen", "XIV": "Fourteen",
        "XV": "Fifteen", "XVI": "Sixteen", "XVII": "Seventeen", "XVIII": "Eighteen",
        "XIX": "Nineteen", "XX": "Twenty"
    }
    def replace_roman(m):
        prefix = m.group(1)
        rn = m.group(2).upper()
        if rn in roman_map:
            return f"{prefix} {roman_map[rn]}"
        return m.group(0)
    text = re.sub(r'\b(Chapter|Part|Section|Book|Modus)\s+([IVXLCDM]+)\b', replace_roman, text, flags=re.IGNORECASE)

    # Years: 1800-2099
    def replace_year(m):
        yr = int(m.group(1))
        if 1800 <= yr <= 2099:
            return num2words(yr, to="year")
        return num2words(yr)
    text = re.sub(r'\b(1[89]\d{2}|20\d{2})\b', replace_year, text)

    # Decimals: 3.5 -> three point five
    def replace_decimal(m):
        whole = num2words(int(m.group(1)))
        dec_digits = " ".join(num2words(int(d)) for d in m.group(2))
        return f"{whole} point {dec_digits}"
    text = re.sub(r'\b(\d+)\.(\d+)\b', replace_decimal, text)

    # Standard comma-separated numbers: 1,500 / 50,000
    text = re.sub(r'\b(\d{1,3}(?:,\d{3})+)\b', lambda m: num2words(int(m.group(1).replace(',', ''))), text)

    # Ordinal numbers: 1st, 2nd, 3rd, 4th, 21st, 24th, etc.
    def replace_ordinal(m):
        num = int(m.group(1))
        return num2words(num, to="ordinal")
    text = re.sub(r'\b(\d+)(?:st|nd|rd|th)\b', replace_ordinal, text, flags=re.IGNORECASE)

    # Standalone numbers
    text = re.sub(r'\b(\d+)\b', lambda m: num2words(int(m.group(1))), text)

    for idx, tag in enumerate(saved_tags):
        text = text.replace(f"__OVTAG_{idx}__", tag)

    return text


def balance_dialogue_quotes(chunk: str) -> str:
    """Ensures quotation marks are balanced per thought chunk to preserve natural prosody."""
    chunk = chunk.strip()
    q_count = chunk.count('"')
    if q_count % 2 == 1:
        if chunk.startswith('"') and not chunk.endswith('"'):
            chunk = chunk + '"'
        elif chunk.endswith('"') and not chunk.startswith('"'):
            chunk = '"' + chunk
        else:
            chunk = chunk.replace('"', '')
    return chunk


def clean_html_and_text(raw_p_html: str) -> str:
    """Parses HTML, cleans dropcaps, normalizes unicode, and sanitizes abbreviations."""
    raw_p_html = mend_hyphenated_linebreaks(raw_p_html)
    text = unescape(raw_p_html)
    parser = PreflightHTMLParser()
    parser.feed(text)
    text = parser.get_text()

    # Heal UTF-8 / Windows-1252 double-encoded mojibake sequences before NFKC and dash replacement
    text = text.replace('â€”', ' -- ').replace('â€“', ' - ').replace('â€¦', '...')
    text = text.replace('â€™', "'").replace('â€˜', "'").replace('â€œ', '"').replace('â€\x9d', '"')
    text = text.replace('â€"', ' -- ').replace('â€', ' -- ')

    text = unicodedata.normalize('NFKC', text)
    text = text.replace('’', "'").replace('‘', "'").replace('`', "'")
    text = text.replace('“', '"').replace('”', '"')
    text = text.replace('—', ' -- ').replace('–', ' - ')
    text = text.replace('‚', 'e')

    # Strip leaked HTML e-reader navigation breadcrumbs (e.g., "Contents - Prev | Next")
    text = re.sub(r'\b(?:Contents\s*[-–—|:]+\s*)?Prev(?:ious)?\s*\|\s*Next\b', ' ', text, flags=re.IGNORECASE)

    # Heal legacy Mac-Roman ellipsis OCR trailing-'c' artifacts (e.g., "Becausec" -> "Because...", "girlc" -> "girl...", "musicc" -> "music...")
    _legit_c_words = {
        "maniac", "pontiac", "havoc", "cognac", "zodiac", "lilac", "almanac", "sumac", "shellac", "bivouac", "prozac",
        "aphrodisiac", "potomac", "lautrec", "luc", "melchisedec", "avec", "bronc", "isaac", "alec", "eric", "marc",
        "arc", "orc", "parc", "torc", "disc", "fisc", "misc", "zinc", "sync", "blanc", "franc", "talc", "calc",
        "etc", "inc", "spec", "rec", "sec", "dec", "exec", "vec", "pec", "doc", "mac", "sac", "pac", "tac", "tic", "toc",
        "roc", "bloc", "hoc", "croc", "floc", "proc", "choc", "sic", "vac", "lac", "mc", "leclerc", "linc", "dunc",
        "malc", "zac", "cadillac", "quebec", "frontenac", "montblanc", "cardiac", "insomniac", "hypochondriac",
        "kleptomaniac", "brainiac", "tarmac", "medevac", "evac", "bric", "brac", "narc", "dulac", "bergerac",
        "merrimac", "chirac", "balzac", "tupac", "anzac", "serac",
    }
    def _heal_trailing_c(m):
        stem = m.group(1)
        full = stem + "c"
        full_lower = full.lower()
        if (
            full_lower in _legit_c_words
            or full == "Bec"
            or (full_lower.endswith(("ic", "iac", "vac")) and not full_lower.endswith("icc"))
        ):
            return m.group(0)
        return stem + "..."
    text = re.sub(r"\b([A-Za-z]{1,})c(?=[\"\'\s,.!?]|$)", _heal_trailing_c, text)
    text = re.sub(r'\b([Ss]o)c(exotic|strange|much|good|bad|long|far|close)\b', r'\1... \2', text)

    # Military, Noble, & Professional Honorific Sanitizer
    text = re.sub(r'\bMr\.\s*', 'Mr ', text)
    text = re.sub(r'\bMrs\.\s*', 'Mrs ', text)
    text = re.sub(r'\bMs\.\s*', 'Ms ', text)
    text = re.sub(r'\bDr\.\s*', 'Dr ', text)
    text = re.sub(r'\bProf\.\s*', 'Prof ', text)
    text = re.sub(r'\bSen\.\s*', 'Senator ', text)
    text = re.sub(r'\bSenator\.\s*', 'Senator ', text)
    text = re.sub(r'\bRep\.\s*', 'Representative ', text)
    text = re.sub(r'\bCol\.\s*', 'Colonel ', text)
    text = re.sub(r'\bCol\b(?=\s+[A-Z])', 'Colonel', text)
    text = re.sub(r'\bGen\.\s*', 'General ', text)
    text = re.sub(r'\bGen\b(?=\s+[A-Z])', 'General', text)
    text = re.sub(r'\bCapt\.\s*', 'Captain ', text)
    text = re.sub(r'\bCapt\b(?=\s+[A-Z])', 'Captain', text)
    text = re.sub(r'\bCmdr\.\s*', 'Commander ', text)
    text = re.sub(r'\bCmdr\b(?=\s+[A-Z])', 'Commander', text)
    text = re.sub(r'\bLt\.\s*Cmdr\.\s*', 'Lieutenant Commander ', text)
    text = re.sub(r'\bLt\.\s*', 'Lieutenant ', text)
    text = re.sub(r'\bLt\b(?=\s+[A-Z])', 'Lieutenant', text)
    text = re.sub(r'\bSgt\.\s*', 'Sergeant ', text)
    text = re.sub(r'\bSgt\b(?=\s+[A-Z])', 'Sergeant', text)
    text = re.sub(r'\bMaj\.\s*', 'Major ', text)
    text = re.sub(r'\bMaj\b(?=\s+[A-Z])', 'Major', text)
    text = re.sub(r'\bAdm\.\s*', 'Admiral ', text)
    text = re.sub(r'\bAdm\b(?=\s+[A-Z])', 'Admiral', text)
    text = re.sub(r'\bGov\.\s*', 'Governor ', text)
    text = re.sub(r'\bRev\.\s*', 'Reverend ', text)
    text = re.sub(r'\bSt\.\s*', 'St ', text)
    text = re.sub(r'\bJr\.\s*', 'Jr ', text)
    text = re.sub(r'\bSr\.\s*', 'Sr ', text)
    text = re.sub(r'\bvs\.\s*', 'versus ', text)
    text = re.sub(r'\be\.g\.\s*', 'for example ', text)
    text = re.sub(r'\bi\.e\.\s*', 'that is ', text)

    # Irish & Celtic Cultural Lexicon (Nora Roberts Gallaghers of Ardmore, Cousins O'Dwyer, Dragon Heart)
    text = re.sub(r'\bc[eé][ií]lis\b', 'kaylees', text, flags=re.IGNORECASE)
    text = re.sub(r'\bc[eé][ií]li\b', 'kaylee', text, flags=re.IGNORECASE)
    text = re.sub(r'\bSl[aá]inte\b', 'Slahn-chuh', text)
    text = re.sub(r'\bsl[aá]inte\b', 'slahn-chuh', text)
    text = re.sub(r'\bbodhr[aá]ns\b', 'bow-rahns', text, flags=re.IGNORECASE)
    text = re.sub(r'\bbodhr[aá]n\b', 'bow-rahn', text, flags=re.IGNORECASE)
    text = re.sub(r'\bSamhain\b', 'SAH-win', text, flags=re.IGNORECASE)
    text = re.sub(r'\bDubheasa\b', 'Duvessa', text, flags=re.IGNORECASE)

    # Star Wars Canon Pronunciation Anchors (Timothy Zahn Thrawn Trilogy)
    text = re.sub(r"\bC['’]baoth['’]s\b", "Sa-bay-oth's", text, flags=re.IGNORECASE)
    text = re.sub(r"\bC['’]baoth\b", "Sa-bay-oth", text, flags=re.IGNORECASE)
    text = re.sub(r"\bCoruscant['’]s\b", "Coru-sahnt's", text, flags=re.IGNORECASE)
    text = re.sub(r"\bCoruscant\b", "Coru-sahnt", text, flags=re.IGNORECASE)

    # Foreign Accented Loanwords & Accents
    text = re.sub(r'\blam[ée]\b', 'lah-may', text, flags=re.IGNORECASE)
    text = re.sub(r'\bCaf[ée]\b', 'Cafe', text)
    text = re.sub(r'\bna[ïi]ve\b', 'naive', text, flags=re.IGNORECASE)
    text = re.sub(r'\bclich[ée]s\b', 'cliches', text, flags=re.IGNORECASE)
    text = re.sub(r'\bclich[ée]\b', 'cliche', text, flags=re.IGNORECASE)
    text = re.sub(r'\bsoir[ée]es\b', 'soirees', text, flags=re.IGNORECASE)
    text = re.sub(r'\bsoir[ée]e\b', 'soiree', text, flags=re.IGNORECASE)
    text = re.sub(r'\bcr[êe]pe\b', 'crepe', text, flags=re.IGNORECASE)
    text = re.sub(r'\bpremi[èe]re\b', 'premiere', text, flags=re.IGNORECASE)

    # Mindfulness / Verbal Disambiguation (Thích Nhất Hạnh Master Collection)
    text = re.sub(r'\bbreath\s+in\b', 'breathe in', text, flags=re.IGNORECASE)
    text = re.sub(r'\bbreath\s+out\b', 'breathe out', text, flags=re.IGNORECASE)
    text = re.sub(r'\bbreath\s+deeply\b', 'breathe deeply', text, flags=re.IGNORECASE)
    text = re.sub(r'\bbreath\s+naturally\b', 'breathe naturally', text, flags=re.IGNORECASE)

    # Geographic & Acronym Spacing
    text = re.sub(r'\bWashington,\s*D\.C\.', 'Washington, D-C', text)
    text = re.sub(r'\bD\.C\.', 'D-C', text)
    text = re.sub(r'\bU\.S\.A\.', 'U-S-A', text)
    text = re.sub(r'\bU\.S\.', 'U-S', text)
    text = re.sub(r'\bU\.S\.S\.', 'U-S-S', text)
    text = re.sub(r'\bC\.I\.A\.', 'C-I-A', text)
    text = re.sub(r'\bCIA\b', 'C-I-A', text)
    text = re.sub(r'\bF\.B\.I\.', 'F-B-I', text)
    text = re.sub(r'\bFBI\b', 'F-B-I', text)
    text = re.sub(r'\bK\.G\.B\.', 'K-G-B', text)
    text = re.sub(r'\bKGB\b', 'K-G-B', text)
    text = re.sub(r'\bA\.M\.', 'A-M', text)
    text = re.sub(r'\bP\.M\.', 'P-M', text)

    # Cyberpunk & Sci-Fi Specific Terminology
    text = re.sub(r'\bICE\b', 'I-C-E', text)
    text = re.sub(r'\bsimstim\b', 'sim stim', text, flags=re.IGNORECASE)
    text = re.sub(r'\bBAMA\b', 'B-A-M-A', text)
    text = re.sub(r'\bkm/s\b', 'kilometers per second', text)
    text = re.sub(r'\bkm/hr\b', 'kilometers per hour', text)
    text = re.sub(r'\bkm\b', 'kilometers', text)
    text = re.sub(r'\bAU\b', 'A-U', text)
    text = re.sub(r'\bMPa\b', 'megapascals', text)

    # Consciousness & Metaphysics Expansions (Robert Monroe & Dolores Cannon)
    text = re.sub(r'\bOBE\b', 'out of body experience', text)
    text = re.sub(r'\bOBEs\b', 'out of body experiences', text)
    text = re.sub(r'\bHemi-Sync\b', 'Hemi Sync', text, flags=re.IGNORECASE)
    text = re.sub(r'\bEEG\b', 'E-E-G', text)
    text = re.sub(r'\bECG\b', 'E-C-G', text)
    text = re.sub(r'\bGSR\b', 'G-S-R', text)
    text = re.sub(r'\bREM\b', 'R-E-M', text)
    text = re.sub(r'\bUFO\b', 'U-F-O', text)
    text = re.sub(r'\bUFOs\b', 'U-F-Os', text)
    text = re.sub(r'\bvol\.\s*', 'volume ', text, flags=re.IGNORECASE)
    text = re.sub(r'\bch\.\s*', 'chapter ', text, flags=re.IGNORECASE)
    text = re.sub(r'\bp\.\s*', 'page ', text, flags=re.IGNORECASE)
    text = re.sub(r'\bpp\.\s*', 'pages ', text, flags=re.IGNORECASE)

    # Contractions
    text = re.sub(r"\b([a-zA-Z]+)'n'\s*([a-zA-Z]+)\b", r"\1 and \2", text)
    text = re.sub(r"\b'cause\b", "because", text)
    text = re.sub(r"\b'em\b", "them", text)

    # URL & Web Link Cleaner
    text = clean_urls_from_text(text)

    # Phonetic Number & Currency Expansion
    text = normalize_numbers_and_currency(text)

    # Mends drop caps and broken inline splits
    text = mend_dropcap_and_inline_splits(text)

    # Clean whitespace & tags
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def clean_urls_from_text(text: str) -> str:
    """Removes web URLs, HTTP/HTTPS links, bare domains, and parenthetical website references for clean audio narration."""
    # 0. Remove bibliographic Source citations referencing websites
    text = re.sub(r'\s*Source:\s*.*?(?:Web\s*site|website).*(?:\.|$)', '', text, flags=re.IGNORECASE)

    # 1. Remove parenthetical website directives pointing to URLs (e.g. (To find..., visit www....) or (For more information, visit ...))
    text = re.sub(r'\s*\([^\)]*?(?:visit|see|available\s+at)\s*(?:https?://|www\.)[^\)]*\)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*\((?:also\s+)?(?:available\s+(?:for\s+free\s+download\s+)?at\s+|see\s+)?https?://[^\)]+\)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*\((?:also\s+)?(?:available\s+(?:for\s+free\s+download\s+)?at\s+|see\s+)?www\.[^\)]+\)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*\(The\s+complete\s+article\s+is\s+available\s+at\s+https?://[^\)]+\.?\)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*\(The\s+complete\s+article\s+is\s+available\s+at\s+www\.[^\)]+\.?\)', '', text, flags=re.IGNORECASE)
    
    # 2. Remove parenthesized URLs like (http://...) or (www....)
    text = re.sub(r'\s*\([hH]ttps?://[^\)]+\)', '', text)
    text = re.sub(r'\s*\(www\.[^\)]+\)', '', text, flags=re.IGNORECASE)

    # 3. Clean 'on its Web site: //http://...' -> 'on its website.'
    text = re.sub(r'(:?\s*(?:on\s+its\s+Web\s+site|at\s+this\s+book\'s\s+Web\s+site):?\s*)\(?/?/?https?://\S+\)?', r'\1', text, flags=re.IGNORECASE)
    text = re.sub(r'(:?\s*(?:on\s+its\s+Web\s+site|at\s+this\s+book\'s\s+Web\s+site):?\s*)\(?/?/?www\.\S+\)?', r'\1', text, flags=re.IGNORECASE)

    # 4. Remove standalone or remaining URLs (http://... or https://... or www....), including broken URLs with whitespace
    text = re.sub(r',?\s*https?://[^\s\)]+(?:\s+[^\s\)]+)*\.(?:org|com|net|gov|edu|html)[^\s\)]*', '', text, flags=re.IGNORECASE)
    text = re.sub(r',?\s*https?://\S+', '', text, flags=re.IGNORECASE)
    text = re.sub(r',?\s*www\.[a-zA-Z0-9_\-\.]+(?:/[^\s,;\)]*)?', '', text, flags=re.IGNORECASE)

    # 5. Clean bare domain references like "Web site healthfinder.gov" -> "Web site Healthfinder"
    text = re.sub(r'(\b(?:Web\s+site|website)\s+)([a-zA-Z0-9_\-]+)\.(?:gov|org|com|net|edu)\b', lambda m: m.group(1) + m.group(2).capitalize(), text, flags=re.IGNORECASE)

    # 6. Clean dangling parentheticals left after URL stripping
    text = re.sub(r'\s*\([^\)]*?(?:visit|see|available\s+at)\s*\)', '', text, flags=re.IGNORECASE)

    # 7. Clean any dangling colons or whitespace before stripped URLs
    text = re.sub(r':\s*([,\.\?!])', r'\1', text)
    text = re.sub(r':\s*$', '.', text, flags=re.MULTILINE)
    text = re.sub(r'\s+([,\.\?!;])', r'\1', text)
    text = re.sub(r'\(\s*\)', '', text)
    text = re.sub(r'  +', ' ', text).strip()
    return text


def extract_and_reflow_paragraphs(raw_html: str, book_title: str = "") -> list[str]:
    """
    Extracts narrative text blocks from HTML and dynamically reflows un-reflowed line wraps.
    Specifically handles:
      1. Fixed-width / OCR line-wrapped EPUBs where each visual line (~8 words) is enclosed in its own <p> tag
         and blank <p>&nbsp;</p> tags represent paragraph breaks.
      2. Mends hyphenated line breaks ('individ-' + 'ual' -> 'individual').
      3. Automatically detects and strips OCR running headers and page numbers
         (e.g., '112 Ben Bova', 'THE WATCHMEN 111', '164 Ben Boca').
      4. Stitches paragraphs across physical page breaks when sentences are split across pages.
      5. Strips OCR artifacts (^ carets, leading backslashes, etc.).
      6. Returns clean, reflowed paragraphs ready for complete-thought sentence splitting.
    """
    # 0. Strip style, script, head, title tags
    cleaned_html = re.sub(r'<style[^>]*>.*?</style>', '', raw_html, flags=re.DOTALL | re.I)
    cleaned_html = re.sub(r'<script[^>]*>.*?</script>', '', cleaned_html, flags=re.DOTALL | re.I)
    cleaned_html = re.sub(r'<head[^>]*>.*?</head>', '', cleaned_html, flags=re.DOTALL | re.I)
    cleaned_html = re.sub(r'</h[1-6]>', '</p><p>&nbsp;</p>', cleaned_html, flags=re.I)
    cleaned_html = re.sub(r'<h[1-6][^>]*>', '<p>', cleaned_html, flags=re.I)

    p_blocks = re.findall(r'<(?:p|div|li)[^>]*>(.*?)</(?:p|div|li)>', cleaned_html, flags=re.DOTALL)
    if not p_blocks:
        p_blocks = [cleaned_html]

    # Check for line-wrapped structure
    non_empty = []
    has_blank_dividers = False
    for p in p_blocks:
        t = re.sub(r'<[^>]+>', '', p).strip()
        t_clean = html.unescape(t).replace('&nbsp;', '').replace('\xa0', '').strip()
        if not t_clean:
            has_blank_dividers = True
        else:
            non_empty.append(t_clean)

    if not non_empty:
        return []

    avg_words = sum(len(t.split()) for t in non_empty) / len(non_empty)
    non_terminal = sum(1 for t in non_empty if not re.search(r'[.!?\"\'”’]$', t) and len(t.split()) > 3)
    ratio = non_terminal / len(non_empty) if non_empty else 0
    # Fixed-width OCR / line-wrapped EPUBs have short lines (< 14 words avg) and high non-terminal ratios (> 25%)
    is_line_wrapped = (avg_words < 14.0) and (ratio > 0.25)

    if not is_line_wrapped:
        results = []
        for p in p_blocks:
            c = clean_html_and_text(p)
            if c:
                results.append(c)
        return results

    # Line-wrapped EPUB reconstruction:
    header_patterns = [
        r'^\d+\s*[-–—]?\s*$',
        r'^(?:(?:\d+\s+)?(?:Ben\s+Bo[uvw][a-z]?|STAR\s+WATCHMAN|THE\s+DUELING\s+MACHINE|THE\s+WATCHMEN))(?:\s+\d+)?$',
        r'^(?:[A-Z\s]{3,35})\s+\d+$',
        r'^\d+\s+(?:[A-Z\s]{3,35})$',
    ]
    if book_title:
        title_esc = re.escape(book_title)
        header_patterns.append(rf'^(?:(?:\d+\s+)?{title_esc})(?:\s+\d+)?$')

    re_headers = [re.compile(p, re.I) for p in header_patterns]

    cleaned_lines = []
    for p in p_blocks:
        t = re.sub(r'<[^>]+>', '', p).strip()
        t = t.replace('&nbsp;', ' ').replace('\xa0', ' ').strip()
        t = re.sub(r'\s+', ' ', t)
        if not t:
            cleaned_lines.append('')
            continue
        if any(rx.match(t) for rx in re_headers):
            continue
        cleaned_lines.append(t)

    grouped_paras = []
    current_lines = []
    for line in cleaned_lines:
        if not line:
            if current_lines:
                joined = current_lines[0]
                for next_l in current_lines[1:]:
                    if joined.endswith('-') and not joined.endswith('--'):
                        joined = joined[:-1] + next_l
                    else:
                        joined = joined + ' ' + next_l
                grouped_paras.append(joined)
                current_lines = []
        else:
            current_lines.append(line)
    if current_lines:
        joined = current_lines[0]
        for next_l in current_lines[1:]:
            if joined.endswith('-') and not joined.endswith('--'):
                joined = joined[:-1] + next_l
            else:
                joined = joined + ' ' + next_l
        grouped_paras.append(joined)

    stitched_paras = []
    for p in grouped_paras:
        p = p.strip()
        if not p:
            continue
        p = re.sub(r'^\\[\s\\]*', '', p)
        p = re.sub(r'(\w+)\s*\^\s*(\w+)', r'\1\2', p)
        p = re.sub(r'\^\s*', '', p)
        p = re.sub(r'•[\*\^r\s%]+', '', p)
        p = re.sub(r'\s+', ' ', p)

        if not stitched_paras:
            stitched_paras.append(p)
            continue

        prev = stitched_paras[-1]
        is_heading_prev = len(prev) < 50 and bool(re.match(r'^(?:PART\s*[IVXLCDM]*|CHAPTER\s*\w*|[IVXLCDM]+|STAR\s+WATCHMAN|THE\s+DUELING\s+MACHINE)\b', prev, re.I))
        is_heading_curr = len(p) < 50 and bool(re.match(r'^(?:PART\s*[IVXLCDM]*|CHAPTER\s*\w*|[IVXLCDM]+|STAR\s+WATCHMAN|THE\s+DUELING\s+MACHINE)\b', p, re.I))
        is_signoff_prev = len(prev) < 40 and any(prev.lower().endswith(x) for x in ['florida', 'connecticut', 'new york', 'ben bova', 'the end', 'finis'])

        next_starts_lower = bool(re.match(r'^[a-z]', p))
        prev_is_hyphen = prev.endswith('-') and not prev.endswith('--')

        if not is_heading_prev and not is_heading_curr and not is_signoff_prev and (prev_is_hyphen or next_starts_lower):
            if prev_is_hyphen:
                stitched_paras[-1] = prev[:-1] + p
            else:
                stitched_paras[-1] = prev + ' ' + p
        else:
            stitched_paras.append(p)

    final_paras = []
    for p in stitched_paras:
        clean = clean_html_and_text(p)
        if clean:
            final_paras.append(clean)

    return final_paras


def _split_long_sentence_cleanly(sentence: str, target_max: int = 280) -> list[str]:
    """Splits a single long sentence (>target_max) along natural grammatical breath boundaries."""
    s = sentence.strip()
    if len(s) <= target_max:
        return [s]

    # Priority 1: Semicolons, colons, or em-dashes
    for delim in ['; ', ': ', ' -- ', ' — ']:
        if delim in s:
            parts = s.split(delim)
            recomb = []
            curr = ''
            for i, p in enumerate(parts):
                unit = (p + delim.rstrip()).strip() if i < len(parts) - 1 else p.strip()
                if not unit:
                    continue
                if len(curr) + len(unit) + 1 <= target_max:
                    curr = (curr + ' ' + unit).strip()
                else:
                    if curr:
                        recomb.extend(_split_long_sentence_cleanly(curr, target_max))
                    curr = unit
            if curr:
                recomb.extend(_split_long_sentence_cleanly(curr, target_max))
            if all(len(c) <= target_max * 1.25 for c in recomb):
                return recomb

    # Priority 2: Commas followed by conjunctions or relative pronouns
    conj_pat = r',\s+(?=(?:and|but|or|nor|for|yet|so|which|who|whom|whose|where|when|while|although|though|because|since|if|as)\b)'
    parts = re.split(conj_pat, s, flags=re.IGNORECASE)
    if len(parts) > 1:
        recomb = []
        curr = ''
        for i, p in enumerate(parts):
            unit = (p + ',').strip() if i < len(parts) - 1 and not p.strip().endswith(',') else p.strip()
            if not unit:
                continue
            if len(curr) + len(unit) + 1 <= target_max:
                curr = (curr + ' ' + unit).strip()
            else:
                if curr:
                    recomb.extend(_split_long_sentence_cleanly(curr, target_max))
                curr = unit
        if curr:
            recomb.extend(_split_long_sentence_cleanly(curr, target_max))
        if all(len(c) <= target_max * 1.3 for c in recomb):
            return recomb

    # Priority 3: Any comma
    if ', ' in s:
        parts = s.split(', ')
        recomb = []
        curr = ''
        for i, p in enumerate(parts):
            unit = (p + ',').strip() if i < len(parts) - 1 else p.strip()
            if not unit:
                continue
            if len(curr) + len(unit) + 1 <= target_max:
                curr = (curr + ' ' + unit).strip()
            else:
                if curr:
                    recomb.extend(_split_long_sentence_cleanly(curr, target_max))
                curr = unit
        if curr:
            recomb.extend(_split_long_sentence_cleanly(curr, target_max))
        if all(len(c) <= target_max * 1.35 for c in recomb):
            return recomb

    # Priority 4: Prepositions or conjunctions without comma
    word_conj_pat = r'\s+(?=(?:and|but|or|which|where|when|while|because|although|with|without|from|into|onto|through)\b)'
    parts = re.split(word_conj_pat, s, flags=re.IGNORECASE)
    if len(parts) > 1:
        recomb = []
        curr = ''
        for p in parts:
            p = p.strip()
            if not p:
                continue
            if len(curr) + len(p) + 1 <= target_max:
                curr = (curr + ' ' + p).strip()
            else:
                if curr:
                    recomb.append(curr)
                curr = p
        if curr:
            recomb.append(curr)
        return recomb

    # Fallback: keep intact rather than chopping words
    return [s]


def split_into_complete_thoughts(paragraph_text: str, max_chars: int = 280) -> list[str]:
    """Splits a paragraph into coherent complete grammatical thoughts (120-280 chars) with balanced quotes."""
    clean_t = paragraph_text.strip()
    if not clean_t:
        return []
    if len(clean_t) <= max_chars:
        return [balance_dialogue_quotes(clean_t)]

    # Clean spacing inside quotes and ellipses
    clean_t = re.sub(r'(^|\s)[\'\"]\s+([A-Za-z0-9])', r"\1'\2", clean_t)
    clean_t = re.sub(r'([A-Za-z0-9\.\,\!\?])\s+[\'\"](\s|$|[\.\,\!\?;:])', r"\1'\2", clean_t)
    clean_t = re.sub(r"\.{3,}\s*\'", r"...'", clean_t)

    # Protect person initials (e.g. 'B. B. King' -> 'B-B King', 'H. L. Mencken' -> 'H-L Mencken')
    clean_t = re.sub(r'\b([A-Z])\.\s*([A-Z])\.\s*', r'\1-\2 ', clean_t)
    clean_t = re.sub(r'\b([A-Z])\.\s+(?=[A-Z][a-z])', r'\1 ', clean_t)

    # Regex protects abbreviations, honorifics, and single-letter initials
    sentences = re.split(
        r'(?<!\bMr)(?<!\bMrs)(?<!\bMs)(?<!\bDr)(?<!\bProf)(?<!\bSen)(?<!\bSenator)'
        r'(?<!\bRep)(?<!\bCol)(?<!\bGen)(?<!\bCapt)(?<!\bCmdr)(?<!\bLt)(?<!\bSgt)(?<!\bMaj)'
        r'(?<!\bAdm)(?<!\bGov)(?<!\bRev)(?<!\bSt)(?<!\bJr)(?<!\bSr)(?<!\bU-S)(?<!\bD-C)'
        r'(?<!\bA-M)(?<!\bP-M)(?<!\bI-C-E)(?<!\b[A-Z]\.)(?<!\b[A-Z]-[A-Z])(?<=[.!?])\s+',
        clean_t
    )

    chunks = []
    current_group = ""

    for s in sentences:
        s = s.strip()
        if not s or s in ["'", '"', '-', '—']:
            continue
        sub_splits = _split_long_sentence_cleanly(s, target_max=max_chars)
        for sub in sub_splits:
            sub = sub.strip()
            if not sub or sub in ["'", '"', '-', '—']:
                continue
            if len(current_group) + len(sub) + 1 <= max_chars:
                current_group = (current_group + " " + sub).strip()
            else:
                if current_group:
                    chunks.append(balance_dialogue_quotes(current_group))
                current_group = sub

    if current_group:
        chunks.append(balance_dialogue_quotes(current_group))

    return chunks


# ── Contextual Paralinguistic Director (OmniVoice v0.5.7+) ───────────────────

_SIGH_ATTRIBUTION_RE = re.compile(
    r'(?:^|\b)(?:he|she|they|[A-Z][a-z]+)\s+(?:let\s+out\s+a\s+(?:long\s+|soft\s+|heavy\s+|deep\s+|weary\s+)?sigh|sighed(?:\s+(?:deeply|softly|wearily|heavily|quietly))?)\b'
    r'|\bwith\s+a\s+(?:long\s+|soft\s+|heavy\s+|deep\s+|weary\s+)?sigh\b',
    re.IGNORECASE,
)

_LAUGH_ATTRIBUTION_RE = re.compile(
    r'(?:^|\b)(?:he|she|they|[A-Z][a-z]+)\s+(?:chuckled(?:\s+softly|\s+quietly)?|laughed\s+softly|gave\s+a\s+(?:soft|short|quiet)\s+(?:laugh|chuckle))\b',
    re.IGNORECASE,
)

_WHISPER_ATTRIBUTION_RE = re.compile(
    r'^"[^"]{3,95}"\s*(?:he|she|they|[A-Z][a-z]+)\s+whispered(?:\s+(?:softly|urgently|quietly|fiercely))?\.?$',
    re.IGNORECASE,
)


def inject_contextual_paralinguistics(text: str, enable_tags: bool = True) -> tuple[str, str | None]:
    """
    Context-aware paralinguistic director for OmniVoice v0.5.7+.
    Examines a sanitized thought chunk and selectively injects native OmniVoice
    inline markers (`[sigh]`, `[laughter]`, `[pause 350ms]`) or returns `instruct="whisper"`
    when prose context explicitly calls for them.

    Returns:
        (directed_text, instruct_style)
    """
    t = text.strip()
    if not enable_tags or not t:
        return t, None

    instruct = None
    if _WHISPER_ATTRIBUTION_RE.match(t):
        instruct = "whisper"

    # 1. Contemplative / meditative breathing cues or dramatic mid-sentence ellipses -> [pause 350ms]
    if "[pause" not in t.lower():
        # Convert mid-thought ellipsis ("Wait... I know" or "Breathe in... and breathe out") into an exact 350ms beat
        t = re.sub(
            r'(\b[A-Za-z]+)\s*\.{3}\s+(?=[A-Za-z\"\'‘“])',
            r'\1... [pause 350ms] ',
            t,
            count=1,
        )

    # 2. Attributed sighs -> inject [sigh] before opening dialogue quote or after sigh clause
    if "[sigh]" not in t.lower() and _SIGH_ATTRIBUTION_RE.search(t):
        if '"' in t:
            t = re.sub(r'"([^"]+)"', r'"[sigh] \1"', t, count=1)
        else:
            t = f"[sigh] {t}"

    # 3. Attributed soft chuckles / laughs -> inject [laughter] before opening dialogue quote
    elif "[laughter]" not in t.lower() and _LAUGH_ATTRIBUTION_RE.search(t) and '"' in t:
        if not re.search(r'\b(?:ha-?ha|he-?he)\b', t, re.IGNORECASE):
            t = re.sub(r'"([^"]+)"', r'"[laughter] \1"', t, count=1)

    t = re.sub(r'\s+', ' ', t).strip()
    return t, instruct
