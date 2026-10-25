"""
OmniVoice Studio Pipeline v3.2 — EPUB Python Tools Integration
Native EPUB Spine Traversal & Clean DOM-Based Story Text Extraction
Powered by ebooklib and BeautifulSoup4 (Zero-Regex HTML Parsing)
"""

import os
import re
import html
import logging
import warnings
from typing import Optional, List, Dict, Tuple
from urllib.parse import unquote
from .normalizer import mend_dropcap_and_inline_splits

logger = logging.getLogger(__name__)

try:
    import ebooklib
    from ebooklib import epub
    HAS_EBOOKLIB = True
except ImportError:
    HAS_EBOOKLIB = False

try:
    from bs4 import BeautifulSoup, Comment, XMLParsedAsHTMLWarning
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
    HAS_BEAUTIFULSOUP = True
except ImportError:
    HAS_BEAUTIFULSOUP = False

from .pure_story_checker import (
    is_frontmatter_text,
    is_backmatter_text,
    sanitize_story_paragraphs,
    FRONTMATTER_HEAD_PATTERNS,
    BACKMATTER_TAIL_PATTERNS
)
from .normalizer import (
    clean_html_and_text,
    extract_and_reflow_paragraphs
)


def extract_clean_paragraphs_from_html(html_content: str | bytes, book_title: str = "") -> List[str]:
    """
    Extracts clean narrative paragraphs from HTML content using BeautifulSoup DOM parsing.
    Eliminates all head metadata, styles, scripts, comments, navigation, and SVG elements.
    Natively decodes HTML entities into Unicode characters and preserves paragraph boundaries.
    """
    if not HAS_BEAUTIFULSOUP:
        content_str = html_content.decode("utf-8", errors="ignore") if isinstance(html_content, bytes) else html_content
        return extract_and_reflow_paragraphs(content_str, book_title=book_title)

    if isinstance(html_content, str):
        content_str = html_content
    else:
        content_str = html_content.decode("utf-8", errors="ignore")

    # Normalize double/multiple <br> tags into paragraph breaks
    content_str = re.sub(r'(?:<br[^>]*>\s*){2,}', '</p><p>', content_str, flags=re.IGNORECASE)
    # Promote styled heading spans into block elements
    content_str = re.sub(r'<span[^>]*class="[^"]*(?:Heading|chapter|title)[^"]*"[^>]*>(.*?)</span>', r'<h2>\1</h2>', content_str, flags=re.IGNORECASE)

    html_bytes = content_str.encode("utf-8")

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore")
        try:
            soup = BeautifulSoup(html_bytes, "lxml")
        except Exception:
            soup = BeautifulSoup(html_bytes, "html.parser")

    # 1. Strip HTML comments
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    # 2. Decompose non-story elements
    for tag in soup(["head", "style", "script", "link", "meta", "nav", "aside", "svg", "footer"]):
        tag.decompose()

    # 3. Replace line breaks with spaces
    for br in soup.find_all(["br", "hr"]):
        br.replace_with(" ")

    # 4. Extract block elements
    paragraphs: List[str] = []
    block_tags = ["p", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "div", "li"]

    for elem in soup.find_all(block_tags):
        # Skip container elements if they have child block elements
        if elem.name in ("div", "blockquote") and elem.find(block_tags):
            continue

        raw_txt = elem.get_text(separator=" ", strip=True)
        if not raw_txt:
            continue

        # Whitespace normalization and dropcap/inline split healing
        clean_txt = re.sub(r"\s+", " ", raw_txt).strip()
        clean_txt = mend_dropcap_and_inline_splits(clean_txt)
        if not clean_txt:
            continue

        # Filter running headers or page numbers (preserve headings)
        if elem.name not in ("h1", "h2", "h3", "h4", "h5", "h6"):
            if re.match(r"^\d+\s*[-–—]?\s*$", clean_txt):
                continue
        # Deduplicate adjacent identical lines (e.g. repeated heading tags)
        if paragraphs and paragraphs[-1].lower() == clean_txt.lower():
            continue

        paragraphs.append(clean_txt)

    if not paragraphs:
        body = soup.find("body") or soup
        text = body.get_text(separator="\n", strip=True)
        lines = [mend_dropcap_and_inline_splits(re.sub(r"\s+", " ", line).strip()) for line in text.split("\n") if line.strip()]
        paragraphs = [line for line in lines if line and not re.match(r"^\d+\s*$", line)]

    return paragraphs


def _get_toc_story_links(book: "epub.EpubBook") -> List[Tuple[str, str]]:
    """Extracts story chapter links from EPUB TOC, filtering out front/backmatter."""
    story_links: List[Tuple[str, str]] = []
    if not hasattr(book, "toc") or not book.toc:
        return story_links

    NON_STORY_KEYWORDS = [
        "cover", "title", "copyright", "contents", "toc", "table of contents", "dear reader",
        "to the reader", "to the readers", "note to the reader",
        "praise", "titles by", "dedication", "epigraph", "acknowledg",
        "about the author", "author's note", "afterword", "foreword",
        "advert", "order books", "newsletter", "also by", "other books",
        "books by", "more by", "connect with", "excerpt", "preview", "bonus", "teaser",
        "cast of characters", "introduction", "preface", "appeal from", "appeal to",
        "translator's note", "translator's notes", "translators note", "translator note",
        "translator", "by the author", "by james s. a. corey", "by james s.a.corey"
    ]

    NON_STORY_HREF_PATTERNS = [
        "appendix", "aboutauthor", "about_author", "abouttheauthor", "advert",
        "ad-", "ad_", "backad", "adcard", "promo", "teaser", "excerpt", "copyright",
        "also_by", "alsoby"
    ]

    def _inspect_item(item):
        if hasattr(item, "title") and hasattr(item, "href"):
            t = (item.title or "").strip()
            h = unquote((item.href or "").split("#")[0].strip())
            if (
                t and h
                and not any(k in t.lower() for k in NON_STORY_KEYWORDS)
                and not any(k in h.lower() for k in NON_STORY_HREF_PATTERNS)
                and not re.match(r"^[\*\s\-_–—]+$", t)
            ):
                story_links.append((t, h))
        elif isinstance(item, (list, tuple)):
            for sub in item:
                _inspect_item(sub)

    toc_items = book.toc if isinstance(book.toc, (list, tuple)) else [book.toc]
    for it in toc_items:
        _inspect_item(it)

    return story_links


EXCLUDE_PATTERNS = [
    "cover", "cvi_", "_cvi", "title", "copyright", "cop_", "_cop", "cop.",
    "dedicat", "contents", "toc", "epigraph",
    "acknowledg", "backad", "adcard", "ad_", "about_author", "aboutauthor",
    "about_the", "publisher", "ata_", "adc_", "col1_", "also_by", "source",
    "readerworks", "advert", "promo", "afterword", "foreword", "frd_", "_frd", "frd.", "preface", "postscript",
    "bibliography", "bibliog", "_bm", "bm1", "bm2", "bm3", "ref_", "references",
    "appendix", "app_", "_app", "appa", "appb", "appc", "appd", "appe", "appf", "appg",
    "notes", "nts_", "_nts", "nts.", "endnote", "footnote", "ftn_", "ftn.",
    "ind_", "_ind", "ind.", "glossary", "loi_", "_loi", "loi.",
    "tea_", "_tea", "tea.", "oeb_tea", "teaser", "elg_", "_elg", "elg.", "oeb_elg", "excerpt",
    "translator", "trans_note"
]


def extract_pure_story_chapters_from_epub(
    epub_path: str,
    book_title: str = "",
    min_chapter_words: int = 150
) -> List[Dict]:
    """
    Parses an EPUB using ebooklib and BeautifulSoup4:
      - Traverses EPUB TOC and OPF Spine reading order.
      - Seamlessly handles multi-file chapter splits and single-file chapters.
      - Discards dedicated frontmatter and backmatter files.
      - Extracts pure story paragraphs without HTML noise.
      - Performs head/tail frontmatter and backmatter sanitization.
    
    Returns:
      List of dicts:
        [
          {
            "chapter_index": 1,
            "chapter_title": "Chapter 01",
            "file_name": "split_001.html",
            "paragraphs": ["...", "..."],
            "word_count": 4350
          },
          ...
        ]
    """
    if not os.path.exists(epub_path):
        raise FileNotFoundError(f"EPUB file not found: {epub_path}")

    if not HAS_EBOOKLIB or not HAS_BEAUTIFULSOUP:
        logger.warning("ebooklib or beautifulsoup4 missing. Falling back to zipfile spine extractor.")
        return _fallback_extract_pure_story(epub_path, book_title=book_title)

    book = epub.read_epub(epub_path)
    meta_title = book.get_metadata("DC", "title")
    resolved_title = meta_title[0][0] if (meta_title and meta_title[0]) else book_title

    # Map spine documents
    spine_doc_names: List[str] = []
    doc_by_name: Dict[str, "epub.EpubItem"] = {}

    for item_id, linear in book.spine:
        item = book.get_item_with_id(item_id)
        if item and item.get_type() == ebooklib.ITEM_DOCUMENT:
            name = item.get_name()
            spine_doc_names.append(name)
            doc_by_name[name] = item

    def resolve_spine_name(href: str) -> Optional[str]:
        h_clean = unquote(href)
        if h_clean in spine_doc_names:
            return h_clean
        h_base = os.path.basename(h_clean)
        for s in spine_doc_names:
            if os.path.basename(s) == h_base:
                return s
        return None

    # Check if TOC provides explicit story chapter boundaries
    toc_story = _get_toc_story_links(book)
    resolved_toc_story: List[Tuple[str, str]] = []
    for t, h in toc_story:
        resolved = resolve_spine_name(h)
        if resolved:
            resolved_toc_story.append((t, resolved))
        else:
            resolved_toc_story.append((t, h))
    toc_story = resolved_toc_story

    use_toc_slicing = (
        len(toc_story) >= 3 and
        sum(1 for _, h in toc_story if h in spine_doc_names) >= max(3, int(len(toc_story) * 0.7))
    )

    raw_chapters: List[Tuple[str, str, List[str]]] = []

    if use_toc_slicing:
        # TOC-based slicing across fine-grained split files (e.g. 235 splits -> 20 chapters)
        for i in range(len(toc_story)):
            ch_title, start_file = toc_story[i]
            end_file = toc_story[i + 1][1] if i + 1 < len(toc_story) else None

            start_idx = spine_doc_names.index(start_file) if start_file in spine_doc_names else -1
            end_idx = spine_doc_names.index(end_file) if (end_file and end_file in spine_doc_names) else len(spine_doc_names)

            if start_idx == -1 or start_idx >= end_idx:
                continue

            start_doc = doc_by_name[start_file]
            sample_paras = extract_clean_paragraphs_from_html(start_doc.get_content(), book_title=resolved_title)
            if sample_paras and (
                any(re.search(r"^a\s+bonus\s+chapter\b", p, re.IGNORECASE) for p in sample_paras[:2])
                or any(re.search(r"^an\s+appeal\s+from\s+vladimir\s+megre\b", p, re.IGNORECASE) for p in sample_paras[:2])
            ):
                continue

            ch_paras: List[str] = []
            for fname in spine_doc_names[start_idx:end_idx]:
                fname_lower = fname.lower()
                # Skip auxiliary frontmatter/backmatter metadata files within the slice
                if fname != start_file:
                    if any(pat in fname_lower for pat in EXCLUDE_PATTERNS):
                        if end_file is None:
                            break
                        continue
                    doc = doc_by_name[fname]
                    test_paras = extract_clean_paragraphs_from_html(doc.get_content(), book_title=resolved_title)
                    if any(is_backmatter_text(p) for p in test_paras[:3]):
                        if end_file is None:
                            break
                        continue
                    if end_file is None and sum(len(p.split()) for p in test_paras) < min_chapter_words:
                        break

                doc = doc_by_name[fname]
                paras = extract_clean_paragraphs_from_html(doc.get_content(), book_title=resolved_title)
                ch_paras.extend(paras)

            if ch_paras:
                raw_chapters.append((ch_title, start_file, ch_paras))

    if not raw_chapters:
        # Standard Document-per-Chapter spine traversal
        for fname in spine_doc_names:
            fname_lower = fname.lower()
            base_name = os.path.basename(fname_lower)

            if any(pat in fname_lower for pat in EXCLUDE_PATTERNS):
                continue
            # Skip split_000 only if it is small frontmatter (< 5000 bytes)
            if re.search(r"split_000\.(?:x?html?|htm)$", base_name):
                if len(doc_by_name[fname].get_content()) < 5000:
                    continue
            if re.match(r"^(?:subject_)?index(?:\.page)?\.(?:x?html?|htm)$", base_name):
                continue

            doc = doc_by_name[fname]
            paras = extract_clean_paragraphs_from_html(doc.get_content(), book_title=resolved_title)
            if not paras:
                continue

            words = sum(len(p.split()) for p in paras)
            if words < min_chapter_words:
                if words < 50 and not (paras and re.match(r"^(?:CHAPTER|PROLOGUE|EPILOGUE)\b", paras[0], re.IGNORECASE)):
                    continue
                if all(is_frontmatter_text(p) for p in paras[:3]):
                    continue

            raw_chapters.append((base_name, fname, paras))

    if not raw_chapters:
        raise ValueError(f"No valid narrative chapters found in EPUB: {epub_path}")

    # Split any multi-chapter files with embedded chapter headings
    HEADING_REGEX = r"^(?:(?:CHAPTER|PROLOGUE|EPILOGUE)(?:\s+(?:[A-Za-z0-9\-]+))?|\d+|(?:ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN|ELEVEN|TWELVE|THIRTEEN|FOURTEEN|FIFTEEN|SIXTEEN|SEVENTEEN|EIGHTEEN|NINETEEN|(?:TWENTY|THIRTY|FORTY)(?:[\s\-]+(?:ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE))?))\s*$"
    expanded_raw_chapters: List[Tuple[str, str, List[str]]] = []
    for title_hint, fname, paras in raw_chapters:
        cur_title = title_hint
        cur_paras: List[str] = []
        for p_idx, p in enumerate(paras):
            is_p_heading = bool(re.match(HEADING_REGEX, p.strip(), flags=re.IGNORECASE))
            if p_idx > 0 and is_p_heading:
                if len(cur_paras) == 1 and re.match(HEADING_REGEX, cur_paras[0].strip(), flags=re.IGNORECASE):
                    cur_title = p.strip()
                    cur_paras = [p]
                    continue
                expanded_raw_chapters.append((cur_title, fname, cur_paras))
                cur_title = p.strip()
                cur_paras = [p]
            else:
                cur_paras.append(p)
        if cur_paras:
            expanded_raw_chapters.append((cur_title, fname, cur_paras))

    # Merge continuation chunks only when NOT using explicit TOC slicing
    if not use_toc_slicing:
        merged_raw_chapters: List[Tuple[str, str, List[str]]] = []
        for t, fn, p in expanded_raw_chapters:
            is_heading = bool(re.match(HEADING_REGEX, t.strip(), re.IGNORECASE) or (p and re.match(HEADING_REGEX, p[0].strip(), re.IGNORECASE)))
            if not is_heading and merged_raw_chapters:
                prev_t, prev_fn, prev_p = merged_raw_chapters[-1]
                merged_raw_chapters[-1] = (prev_t, prev_fn, prev_p + p)
            else:
                merged_raw_chapters.append((t, fn, p))
        raw_chapters = merged_raw_chapters
    else:
        raw_chapters = expanded_raw_chapters

    # Drop leading frontmatter chunk if it has no chapter heading and is below minimum chapter length
    if raw_chapters:
        ch0_words = sum(len(p.split()) for p in raw_chapters[0][2])
        if ch0_words < min_chapter_words and not re.match(HEADING_REGEX, raw_chapters[0][0], re.IGNORECASE) and not (raw_chapters[0][2] and re.match(HEADING_REGEX, raw_chapters[0][2][0], re.IGNORECASE)):
            raw_chapters.pop(0)

    # Head and Tail sanitization across chapters
    story_chapters: List[Dict] = []
    total_chaps = len(raw_chapters)

    for idx, (title_hint, fname, paras) in enumerate(raw_chapters):
        ch_num = idx + 1
        is_first = (idx == 0)
        is_last = (idx == total_chaps - 1)

        sanitized_paras = sanitize_story_paragraphs(
            paras,
            is_first_chapter=is_first,
            is_last_chapter=is_last,
            book_title=resolved_title
        )

        if not sanitized_paras:
            continue

        # Format Chapter Title
        first_p = sanitized_paras[0] if sanitized_paras else ""
        if re.match(r"^(?:Chapter\s+\d+|Prologue|Epilogue|Book\s+\d+|Part\s+\d+|Section\s+\d+)\b", first_p, flags=re.IGNORECASE) and len(first_p.split()) <= 6:
            chapter_title = first_p
        elif re.match(r"^\d+$", first_p.strip()):
            chapter_title = f"Chapter {int(first_p):02d}"
        elif re.match(r"^(?:Chapter\s+(\d+)|Prologue|Epilogue)\b", title_hint, flags=re.IGNORECASE):
            m_hint = re.match(r"^(?:Chapter\s+(\d+)|Prologue|Epilogue)\b", title_hint, flags=re.IGNORECASE)
            if m_hint.group(1):
                chapter_title = f"Chapter {int(m_hint.group(1)):02d}"
            else:
                chapter_title = m_hint.group(0).capitalize()
        elif re.match(r"^(?:ONE|TWO|THREE|FOUR|FIVE|SIX|SEVEN|EIGHT|NINE|TEN|ELEVEN|TWELVE|THIRTEEN|FOURTEEN|FIFTEEN|SIXTEEN|SEVENTEEN|EIGHTEEN|NINETEEN|TWENTY)\b", title_hint, flags=re.IGNORECASE):
            chapter_title = f"Chapter {ch_num:02d} - {title_hint.capitalize()}"
        else:
            chapter_title = f"Chapter {ch_num:02d}"

        story_chapters.append({
            "chapter_index": ch_num,
            "chapter_title": chapter_title,
            "file_name": fname,
            "paragraphs": sanitized_paras,
            "word_count": sum(len(p.split()) for p in sanitized_paras)
        })

    return story_chapters


def _fallback_extract_pure_story(epub_path: str, book_title: str = "") -> List[Dict]:
    """Fallback extractor using zipfile when ebooklib is not available."""
    import zipfile
    from .pure_story_checker import get_epub_spine_story_files

    story_files = get_epub_spine_story_files(epub_path)
    zf = zipfile.ZipFile(epub_path, "r")
    chapters = []

    for idx, fname in enumerate(story_files):
        ch_num = idx + 1
        try:
            raw_html = zf.read(fname).decode("utf-8", errors="ignore")
        except Exception:
            continue

        paras = extract_and_reflow_paragraphs(raw_html, book_title=book_title)
        is_first = (idx == 0)
        is_last = (idx == len(story_files) - 1)
        sanitized = sanitize_story_paragraphs(paras, is_first_chapter=is_first, is_last_chapter=is_last, book_title=book_title)

        if sanitized:
            chapters.append({
                "chapter_index": ch_num,
                "chapter_title": f"Chapter {ch_num:02d}",
                "file_name": fname,
                "paragraphs": sanitized,
                "word_count": sum(len(p.split()) for p in sanitized)
            })

    return chapters
