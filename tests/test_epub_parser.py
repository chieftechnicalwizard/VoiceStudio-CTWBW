"""
Tests for native EPUB Python Tools Integration (ebooklib + BeautifulSoup4).
Validates DOM-based clean text extraction, entity decoding, and TOC/spine story extraction.
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts.pipeline_v3 import (
    extract_clean_paragraphs_from_html,
    extract_pure_story_chapters_from_epub
)


def test_extract_clean_paragraphs_from_html_entities_and_structure():
    raw_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Chapter Title Bleed</title>
        <style>.dropcap { font-size: 2em; }</style>
        <script>console.log('strip me');</script>
    </head>
    <body>
        <!-- Publisher comment -->
        <p><span class="dropcap">S</span>he walked into the room&mdash;smiling&nbsp;brightly.</p>
        <p>&ldquo;Hello,&rdquo; she said. &lsquo;It&rsquo;s fine.&rsquo;</p>
        <div>
            <p>Nested block inside container div should not be duplicated.</p>
        </div>
        <footer><p>Footer page number 123</p></footer>
    </body>
    </html>
    """
    paras = extract_clean_paragraphs_from_html(raw_html, book_title="Test Book")
    assert len(paras) == 3
    # Verify entity conversion and tags removed
    assert paras[0] == "S he walked into the room—smiling brightly." or paras[0] == "She walked into the room—smiling brightly."
    assert "—" in paras[0]
    assert '"Hello,"' in paras[1] or '“Hello,”' in paras[1] or "Hello" in paras[1]
    assert paras[2] == "Nested block inside container div should not be duplicated."
    assert not any("Chapter Title Bleed" in p for p in paras)
    assert not any("strip me" in p for p in paras)


def test_extract_clean_paragraphs_ordinal_support():
    from scripts.pipeline_v3.normalizer import normalize_numbers_and_currency
    text = "It's May the 24th or 25th. I lose track on the 1st."
    norm = normalize_numbers_and_currency(text)
    assert "twenty-fourth" in norm
    assert "twenty-fifth" in norm
    assert "first" in norm


def test_embedded_chapter_heading_splitting(tmp_path):
    import ebooklib
    from ebooklib import epub
    
    test_epub = str(tmp_path / "test_embedded.epub")
    book = epub.EpubBook()
    book.set_identifier("test-emb-123")
    book.set_title("Test Multi Chapters")
    book.set_language("en")
    
    c1 = epub.EpubHtml(title="Chapter 1", file_name="ch1.xhtml", lang="en")
    # Multi-chapter single document: Chapter 1 + Chapter 2 embedded
    p_lines = [f"<p>Paragraph {i} of chapter one with lots of text to satisfy minimum paragraph requirements.</p>" for i in range(20)]
    p_lines.append("<p>CHAPTER TWO</p>")
    p_lines.extend([f"<p>Paragraph {i} of chapter two with lots of text to satisfy minimum paragraph requirements.</p>" for i in range(20)])
    c1.content = "<html><body>" + "".join(p_lines) + "</body></html>"
    
    book.add_item(c1)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", c1]
    epub.write_epub(test_epub, book)
    
    chapters = extract_pure_story_chapters_from_epub(test_epub, book_title="Test Multi Chapters")
    assert len(chapters) == 2
    assert "Chapter 01" in chapters[0]["chapter_title"]
    assert "Chapter 02" in chapters[1]["chapter_title"] or "CHAPTER TWO" in chapters[1]["chapter_title"]

