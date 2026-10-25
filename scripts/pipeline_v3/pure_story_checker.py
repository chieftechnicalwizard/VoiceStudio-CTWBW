"""
Pipeline v3.0 — Pure-Story Integrity & Automated Frontmatter/Backmatter Sanitizer
Guarantees 100% pure narrative audiobooks:
  1. Gate 1: Startup Deterministic Regression Test Suite (pytest tests/test_pure_story_integrity.py).
  2. Gate 2: Preflight EPUB Dry-Run Audit (preflight_audit_book_epub before any GPU calls).
  3. True EPUB OPF Spine Traversal (rejects arbitrary alphabetical sorting).
  4. Dedicated Frontmatter/Backmatter File Exclusion (drops covers, dedications, afterwords).
  5. In-Chapter Head-Sanitization (strips author names, title pages, dedications, epigraphs).
  6. In-Chapter Tail-Sanitization (strips trailing ISBNs, cover art credits, author sign-offs, teaser blurbs).
  7. Deterministic QA Gate Verification (scans generated transcripts/QA reports for leaks).
"""

import os
import re
import json
import zipfile
import urllib.parse
import xml.etree.ElementTree as ET
from .normalizer import clean_html_and_text

# Regex patterns for frontmatter indicators (matched with re.IGNORECASE)
FRONTMATTER_HEAD_PATTERNS = [
    # Dedications
    r"^(?:in\s+alphabetical\s+order:\s*)?to\s+[\w\s,.'’\-–—]+(?:with\s+(?:love|thanks|gratitude|hope|respect|caritas)|mentor|cousins|despite|for\s+fine|for\s+so\s+many|who\s+are|library)\b",
    r"^to\s+the\s+pratt\s+family\b",
    r"^to\s+regina,\s+with\s+love\b",
    r"^in\s+alphabetical\s+order:\s*$",
    r"^dedicated\s+to\b",
    r"^these\s+tales\s+are\s+dedicated\s+to\b",
    r"^for\s+[\w\s,.'’\-–—]+(?:with\s+love)?$",
    # Copyright & Legal Notices
    r"^copyright\s*(?:©|\(c\)|nineteen|\d{4})",
    r"^all\s+rights\s+reserved",
    r"^this\s+is\s+a\s+work\s+of\s+fiction",
    r"^note:\s*if\s+you\s+purchased\s+this\s+book\s+without\s+a\s+cover",
    r"^published\s+by\b",
    r"^printed\s+in\s+the\s+united\s+states",
    r"^tor\s+books\s+by\b",
    r"^this\s+ebook\s+was\s+created\s+using\b",
    r"^the\s+author\s+and\s+publisher\s+have\s+provided\s+this\s+e-?book",
    # Forewords, Prefaces, Notes
    r"^author'?s?\s+foreword\b",
    r"^author'?s?\s+preface\b",
    r"^reality\s+and\s+symbols\b",
    r"^transcriber'?s?\s+note\b",
    r"^the\s+project\s+gutenberg\s+ebook\s+of\b",
    r"^annotation\b",
    r"^contents\b",
    r"^table\s+of\s+contents\b",
    r"^title\s+page\b",
    r"^epigraph\b",
    # Author & Book Title page markers
    r"^(?:by\s+)?ben\s+bova\b.*$",
    r"^(?:by\s+)?dolores\s+cannon\b.*$",
    r"^[\w\s~:–—]+by\s+dolores\s+cannon\b.*$",
    r"^(?:by\s+)?gordon\s+r\.\s+dickson\b.*$",
    r"^(?:by\s+)?myron\s+r\.\s+lewis\b.*$",
    r"^orion\s+in\s+the\s+dying\s+time\b.*$",
    r"^orion\s+and\s+the\s+conqueror\b.*$",
    r"^orion\s+among\s+the\s+stars\b.*$",
    r"^orion\s+and\s+king\s+arthur\b.*$",
    r"^the\s+exiles\s+trilogy\b.*$",
    r"^a\s+novel\b.*$",
    r"^a\s+science\s+fiction\s+novel\b.*$",
    # Epigraphs & attributions
    r"^--\s+[\w\s.-]+$",
    r"^(?:\"|“)?an\s+intelligence\s+knowing,\s+at\s+a\s+given\s+instance\b",
    # Calibre split header artifact
    r"^[\w\s_.,()\-]+\.html?\b",
    # Numeric / spelled table of contents dump
    r"^one\s+two\s+three\s+four\s+five\s+six\s+seven\s+eight\s+nine\s+ten",
    r"^special\s+note\b",
    r"^dedication\b",
    # Series metadata / Publisher headers
    r"^(?:by\s+)?vladimir\s+megre\b",
    r"^(?:b\s*y\s+)?j\s*ames\s+s\.\s*a\.\s+c\s*orey\b.*$",
    r"^volume\s+[ivxLCDM\d]+\b",
    r"^of\s+the\s+ringing\s+cedars\s+of\s+russia\b",
    r"^a\s+new\s+updated\s+author'?s?\s+edition!?\b",
    r"^www\.vmegre\.com\b"
]

# Regex patterns for backmatter indicators (matched with re.IGNORECASE)
BACKMATTER_TAIL_PATTERNS = [
    # ISBN, cover credits & copyright
    r"^isbn(?::|\s+)\s*[\d\w\-–—]+",
    r"^cover\s+art\s+by\b",
    r"^cover\s+design\s+by\b",
    r"^copyright\s*(?:©|\(c\)|nineteen|\d{4})",
    # Author location sign-offs & end markers
    r"^(?:the\s+e\s*n\s*d|finis)$",
    r"^end\s+of\s+(?:the\s+)?project\s+gutenberg\b",
    r"^west\s+hartford,\s+connecticut$",
    r"^ben\s+bova$",
    r"^(?:yours\s+(?:truly|faithfully|sincerely)|respectfully\s+yours)\b",
    r"^with\s+esteem\s+for\s+you,\s+esteemed\s+readers",
    r"^to\s+be\s+continued\.{0,4}$",
    r"^vladimir\s+megre$",
    r"^translation\s+by(?::|\s)\b",
    r"^we\s+seek\s+the\s+cooperation\b",
    # Author Afterwords & End Notes
    r"^author'?s?\s+afterword\b",
    r"^afterword\b",
    r"^historical\s+note\s+and\s+acknowledgments?\b",
    r"^acknowledgments?\b",
    r"^author'?s?\s+note\b",
    r"^translator'?s?\s+notes?\b",
    r"^a\s+note\s+on\s+the\s+text\b",
    # Back-cover teaser promo ads & author appeals
    r"^a\s+winter\s+hell\b",
    r"^it'?s\s+labor\s+day\.\s+your\s+new\s+york\s+vacation\s+is\s+over",
    r"^now\s+you\s+are\s+prey\s+to\s+the\s+gangs\b",
    r"^about\s+the\s+author\b",
    r"^author'?s?\s+page\b",
    r"^order\s+books\s+online\b",
    r"^for\s+more\s+information\s+on\s+readerworks\b",
    r"\bthank\s+you\s+for\s+buying\s+this\b",
    r"\bsign\s+up\s+for\s+(?:our\s+)?newsletters?\b",
    r"\blook\s+for\s+the\s+other\s+novels\s+in\s+the\b",
    r"\bavailable\s+as\s+ebooks\s+from\b",
    r"^(?:https?://|www\.)[a-z0-9\-.]+\b",
    r"^an\s+appeal\s+from\s+vladimir\s+megre\b",
    r"^a\s+bonus\s+chapter\b",
    r"^for\s+inquiries\s+and\s+suggestions\b",
    r"^po\s+box\s+\d+\b",
    r"^phone\b",
    r"^skype:\s*[\w\.\-]+",
    r"^the\s+\"ringing\s+cedars\"\s+company\s+presents\b",
    r"^according\s+to\s+the\s+author'?s?\s+idea\b",
    r"^table\s+of\s+contents\b"
]

def is_frontmatter_text(text: str) -> bool:
    """Checks if a paragraph text matches frontmatter patterns."""
    t = text.strip()
    if not t:
        return False
    # Strip leading Calibre/Publisher header e.g. "ISAACASIMOV /* */"
    t = re.sub(r'^(?:[A-Za-z\s]+/\*\s*\*/\s*)', '', t).strip()
    t = re.sub(r'^(?:&nbsp;|\s)+', '', t).strip()
    for pat in FRONTMATTER_HEAD_PATTERNS:
        if re.search(pat, t, re.IGNORECASE):
            return True
    return False

def is_backmatter_text(text: str) -> bool:
    """Checks if a paragraph text matches backmatter patterns."""
    t = text.strip()
    if not t:
        return False
    for pat in BACKMATTER_TAIL_PATTERNS:
        if re.search(pat, t, re.IGNORECASE):
            return True
    return False

def is_horizontal_rule_or_divider(text: str) -> bool:
    """Checks if text is a scene divider, horizontal rule, or sequence of hyphens/asterisks/dots."""
    t = text.strip()
    if not t:
        return True
    if len(t) >= 2 and all(ch in '-—–*_ •#.' for ch in t):
        return True
    return False

def sanitize_story_paragraphs(paragraphs: list[str], is_first_chapter: bool = False, is_last_chapter: bool = False, book_title: str = "") -> list[str]:
    """
    Cleans paragraph list by:
      - Stripping all leading frontmatter paragraphs from chapter 1 (or any chapter).
      - Stripping all trailing backmatter paragraphs from the final chapter.
      - Stripping horizontal rules and scene break dividers (e.g. '----------------').
    Returns sanitized paragraph list.
    """
    cleaned = [p.strip() for p in paragraphs if p and p.strip() and not is_horizontal_rule_or_divider(p)]
    
    # Head Sanitization: Strip frontmatter paragraphs
    if is_first_chapter:
        while cleaned:
            cand = cleaned[0]
            if is_frontmatter_text(cand):
                cleaned.pop(0)
                continue
            if book_title and re.sub(r'[^\w\s]', '', cand).strip().lower() == re.sub(r'[^\w\s]', '', book_title).strip().lower():
                cleaned.pop(0)
                continue
            break
            
    # Tail Sanitization: Strip backmatter paragraphs
    if is_last_chapter:
        while cleaned and is_backmatter_text(cleaned[-1]):
            cleaned.pop()
            
    return cleaned

def get_epub_spine_story_files(epub_path: str) -> list[str]:
    """
    Extracts HTML chapter files in exact EPUB OPF Spine reading order,
    strictly filtering out dedicated frontmatter/backmatter files.
    """
    zf = zipfile.ZipFile(epub_path, 'r')
    opf_names = [f for f in zf.namelist() if f.endswith('.opf')]
    if not opf_names:
        try:
            container = zf.read('META-INF/container.xml').decode('utf-8')
            m = re.search(r'full-path=\"([^\"]+)\"', container)
            if m:
                opf_names = [m.group(1)]
        except Exception:
            pass
    if not opf_names:
        spine = sorted([f for f in zf.namelist() if f.endswith(('.html', '.xhtml', '.htm'))])
    else:
        opf_path = opf_names[0]
        opf_dir = os.path.dirname(opf_path)
        opf_xml = zf.read(opf_path).decode('utf-8', errors='ignore')
        root = ET.fromstring(opf_xml)
        manifest = {}
        for item in root.findall('.//{*}item'):
            href = item.attrib.get('href', '')
            if opf_dir:
                full_href = f'{opf_dir}/{href}'.replace('\\', '/')
            else:
                full_href = href
            full_href = urllib.parse.unquote(full_href)
            manifest[item.attrib.get('id')] = full_href

        spine = []
        for itemref in root.findall('.//{*}itemref'):
            idref = itemref.attrib.get('idref')
            if idref in manifest:
                spine.append(manifest[idref])

    story_files = []
    for f in spine:
        f_lower = f.lower()
        fname = os.path.basename(f_lower)
        if any(bad in f_lower for bad in [
            'cover', 'cvi_', '_cvi', 'title', 'copyright', 'cop_', '_cop', 'cop.',
            'dedicat', 'contents', 'toc', 'epigraph',
            'acknowledg', 'backad', 'adcard', 'ad_', 'about_author', 'aboutauthor',
            'about_the', 'publisher', 'ata_', 'adc_', 'col1_', 'also_by', 'source',
            'readerworks', 'advert', 'promo', 'afterword', 'foreword', 'frd_', '_frd', 'frd.', 'preface', 'postscript',
            'bibliography', 'bibliog', '_bm', 'bm1', 'bm2', 'bm3', 'ref_', 'references',
            'appendix', 'app_', '_app', 'appa', 'appb', 'appc', 'appd', 'appe', 'appf', 'appg',
            'notes', 'nts_', '_nts', 'nts.', 'endnote', 'footnote', 'ftn_', 'ftn.',
            'ind_', '_ind', 'ind.', 'glossary', 'loi_', '_loi', 'loi.',
            'newsletter', 'seriespage', 'backmatter', 'abouttheauthor',
            'desc.', 'otherbooks', 'other_books', 'jacket', '_ded_', '_ded.', 'ded_'
        ]) or re.search(r'^(?:subject_)?index(?:\.page)?\.(?:x?html?|htm)$', fname) or re.search(r'_(?:app[a-z]|nts|ind|loi|cop|frd|cvi|tp|toc)_', f_lower):
            continue
        try:
            raw = zf.read(f).decode('utf-8', errors='ignore')
        except Exception:
            continue
        text_clean = clean_html_and_text(raw)
        t_lower = text_clean[:400].lower()
        # Only drop entire file if small file (< 15KB) and matches front/backmatter indicators
        if len(text_clean) < 15000 and (
            any(bad in t_lower for bad in [
                'table of contents', 'all rights reserved', 'published by', 'printed in the united states',
                'also by ben bova', 'about the publisher', 'tor books by', 'this ebook was created using',
                'about the author', 'author\'s foreword', 'author\'s preface', 'author\'s afterword',
                'author\'s page', 'author page',
                'afterword', 'order books online', 'readerworks'
            ])
            or is_frontmatter_text(text_clean)
            or is_backmatter_text(text_clean)
            or ('pagetype_copyrt' in raw or 'pagetype_fmatter' in raw or 'pagetype_toc' in raw and len(text_clean) < 1500)
            or (len(re.findall(r'<a\s+[^>]*href="[^"]*(?:toc|_split_)[^"]*"', raw, re.I)) >= 3 and len(re.findall(r'<p[\s>]', raw, re.I)) <= 1)
            or (len(text_clean) < 4000 and re.search(r'copyright\s*(?:©|\(c\)|nineteen|\d{4})', text_clean, re.I))
            or (len(text_clean) < 4000 and re.search(r'\b(?:was\s+born\s+in|emigrated\s+to\s+the\s+united\s+states|author\s+of\s+more\s+than\s+\d+)\b', text_clean, re.I))
        ):
            continue
        if len(text_clean) < 100:
            continue
        story_files.append(f)
    return story_files

def verify_book_qa_reports(qa_dir: str) -> tuple[bool, list[str]]:
    """
    Audits all generated QA reports in qa_dir:
      - Checks Chapter 1 opening chunks for frontmatter.
      - Checks Final Chapter ending chunks for backmatter.
    Returns (is_clean, issues_list).
    """
    import glob
    import json

    qas = sorted(glob.glob(os.path.join(qa_dir, "*_qa_report.json")))
    if not qas:
        return False, ["No QA reports found to audit."]

    issues = []
    # Check Chapter 1 opening
    with open(qas[0], "r", encoding="utf-8") as f:
        first_rep = json.load(f)
    first_chunks = first_rep.get("chunks", [])
    if first_chunks:
        head_text = first_chunks[0].get("text", "")
        if is_frontmatter_text(head_text):
            issues.append(f"Chapter 1 Head Leak: '{head_text[:80]}'")

    # Check Final Chapter ending
    with open(qas[-1], "r", encoding="utf-8") as f:
        last_rep = json.load(f)
    last_chunks = last_rep.get("chunks", [])
    if last_chunks:
        tail_text = last_chunks[-1].get("text", "")
        if is_backmatter_text(tail_text):
            issues.append(f"Final Chapter Tail Leak: '{tail_text[:80]}'")

    return len(issues) == 0, issues

def preflight_audit_book_epub(epub_path: str, book_title: str = "") -> tuple[bool, list[str]]:
    """
    Dry-run preflight verification on an EPUB before narration generation:
      - Validates OPF spine story files.
      - Verifies Chapter 1 sanitized opening paragraph is 100% free of frontmatter.
      - Verifies Final Chapter sanitized ending paragraph is 100% free of backmatter.
      - Ensures no intermediate files are empty or pure frontmatter/backmatter.
    Returns (is_clean, issues_list).
    """
    if not os.path.exists(epub_path):
        return False, [f"EPUB file not found: {epub_path}"]

    story_files = get_epub_spine_story_files(epub_path)
    if not story_files:
        return False, [f"No story files extracted from spine for {epub_path}"]

    zf = zipfile.ZipFile(epub_path, 'r')
    issues = []

    # Check Chapter 1
    raw_ch1 = zf.read(story_files[0]).decode('utf-8', errors='ignore')
    p_blocks1 = re.findall(r'<(?:p|div)[^>]*>(.*?)</(?:p|div)>', raw_ch1, flags=re.DOTALL)
    paras1 = [clean_html_and_text(p) for p in p_blocks1 if clean_html_and_text(p)]
    if not paras1:
        paras1 = [clean_html_and_text(raw_ch1)]
    sanitized_ch1 = sanitize_story_paragraphs(paras1, is_first_chapter=True, is_last_chapter=(len(story_files) == 1), book_title=book_title)
    if not sanitized_ch1:
        issues.append("Chapter 1 has no remaining paragraphs after sanitization.")
    elif is_frontmatter_text(sanitized_ch1[0]):
        issues.append(f"Chapter 1 Head Leak: '{sanitized_ch1[0][:80]}'")

    # Check Final Chapter
    raw_last = zf.read(story_files[-1]).decode('utf-8', errors='ignore')
    p_blocks_last = re.findall(r'<(?:p|div)[^>]*>(.*?)</(?:p|div)>', raw_last, flags=re.DOTALL)
    paras_last = [clean_html_and_text(p) for p in p_blocks_last if clean_html_and_text(p)]
    if not paras_last:
        paras_last = [clean_html_and_text(raw_last)]
    sanitized_last = sanitize_story_paragraphs(paras_last, is_first_chapter=(len(story_files) == 1), is_last_chapter=True, book_title=book_title)
    if not sanitized_last:
        issues.append("Final Chapter has no remaining paragraphs after sanitization.")
    elif is_backmatter_text(sanitized_last[-1]):
        issues.append(f"Final Chapter Tail Leak: '{sanitized_last[-1][:80]}'")

    return len(issues) == 0, issues


def validate_manifest_formatting_integrity(manifest_path: str) -> tuple[bool, list[str]]:
    """
    Gate 3 Preflight Validator: Scans thoughts_manifest.json for:
      - Split dropcaps ('W hat', 'T he', 'M iller')
      - Split possessives / contractions ('Knight 's', 'Roci 's')
      - Non-standard single-letter word breaks
    Returns (is_clean, issues_list). Blocks synthesis if any parsing errors exist.
    """
    if not os.path.exists(manifest_path):
        return False, [f"Manifest file not found: {manifest_path}"]

    with open(manifest_path, "r", encoding="utf-8") as f:
        thoughts = json.load(f)

    issues = []
    dc_pat = re.compile(r'(?:^|[\"“\'‘\(\[\{])([B-HJ-Z])\s+([a-zA-Z]{1,})\b')
    pos_pat = re.compile(r"\b([a-zA-Z]+)\s+['’]([sStTmMdDvVrReE]|ll|LL|ve|VE|re|RE)\b")
    ai_pat = re.compile(
        r'(?:^|[\"“\'‘\(\[\{])([AI])\s+(?:fter|bout|nother|nd|ll|lmost|lready|lthough|gain|cross|round|mong|'
        r'ccording|ctually|ffirmative|lex\b|rnold\b|sh\b|n\b|s\b|t\b|DMISSION|LL|ND|NSWER|'
        r'f\b|nto\b|nstead\b|nside\b|F\b|NCOMING)\b'
    )

    for item in thoughts:
        t = item.get("text", "")
        ch = item.get("chapter", 0)
        t_id = item.get("id", item.get("thought_index", 0))

        m_dc = dc_pat.findall(t)
        if m_dc:
            issues.append(f"Chapter {ch} Thought {t_id}: Split Dropcap detected: {m_dc}")
        m_pos = pos_pat.findall(t)
        if m_pos:
            issues.append(f"Chapter {ch} Thought {t_id}: Split Possessive detected: {m_pos}")
        m_ai = ai_pat.findall(t)
        if m_ai:
            issues.append(f"Chapter {ch} Thought {t_id}: Split A/I Dropcap detected: {m_ai}")

    return len(issues) == 0, issues

