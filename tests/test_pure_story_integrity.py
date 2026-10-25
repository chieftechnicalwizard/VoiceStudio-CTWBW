"""
Deterministic Regression Test Suite — Pure Story Integrity & Frontmatter/Backmatter Elimination
Validates:
  1. Accurate detection and stripping of all publisher frontmatter (dedications, copyright, calibre artifacts, forewords).
  2. Accurate detection and stripping of all backmatter (ISBNs, cover art credits, author sign-offs, teaser blurbs).
  3. Real story paragraphs are never falsely stripped.
  4. True EPUB OPF Spine order is maintained without alphabetical scrambling.
"""

import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from scripts.pipeline_v3.pure_story_checker import (
    is_frontmatter_text,
    is_backmatter_text,
    sanitize_story_paragraphs,
    get_epub_spine_story_files
)

def test_frontmatter_detection_dedications():
    frontmatter_samples = [
        "To the Pratt family, with thanks for fine times.",
        "To Regina, with love and hope for a better tomorrow.",
        "In alphabetical order: To Gordon R. Dickson and Harlan Ellison with thanks and caritas.",
        "To the kindly, courteous, cheerful, and always-helpful staff of the West Hartford Public Library",
        "To Mark Chartrand, despite his puns",
        "These tales are dedicated to the entrepreneurs who are striving to open the space frontier",
        "Dedicated to the memory of my father",
        "To Bella Sue Martin and Jim Parsons, for so many reasons"
    ]
    for sample in frontmatter_samples:
        assert is_frontmatter_text(sample), f"Failed to detect dedication: {sample}"

def test_frontmatter_detection_legal_and_notes():
    frontmatter_samples = [
        "Copyright © nineteen eighty-four by Ben Bova",
        "Copyright (C) 1990 by Ben Bova. All rights reserved.",
        "This is a work of fiction. All the characters and events portrayed in this book are fictional.",
        "NOTE: If you purchased this book without a cover you should be aware that this book is stolen property.",
        "Published by Tor Books, New York.",
        "Printed in the United States of America.",
        "TOR BOOKS BY BEN BOVA",
        "This eBook was created using ReaderWorks(TM) Standard, produced by OverDrive, Inc.",
        "Author's Foreword: Reality and Symbols",
        "Author's Preface",
        "Transcriber's Note: This etext was produced from Analog Science Fact & Fiction",
        "The Project Gutenberg EBook of The Dueling Machine",
        "Annotation Suppose that elves, gremlins, and leprechauns are really tiny aliens",
        "Table of Contents",
        "BenBova-(ExilesTrilogy01)ExiledFromEarthv0.six(nineteen seventy-one).html",
        "one two three four five six seven eight nine ten eleven twelve thirteen fourteen"
    ]
    for sample in frontmatter_samples:
        assert is_frontmatter_text(sample), f"Failed to detect legal/foreword frontmatter: {sample}"

def test_story_paragraphs_not_false_positives():
    real_story_samples = [
        "FROM THE REAR SEAT of the TF-fifteen jet the mountains of Utah looked like barren wrinkles of grayish brown.",
        "BEIJING",
        "Chiang Chantao sat in his powerchair, floating high above the flooded city of St Louis.",
        "I am not superhuman.",
        "The glass was cold.",
        "Linc rubbed at it with the heel of his hand and felt the coldness of death sucking at his fingertips.",
        "The General Chairman paced across the soft carpeting of his office, hands clasped behind his back.",
        "Fire... it's on fire !",
        "Chattanooga, Tennessee",
        "Hank Barstow frowned at the blank screen of his GPS box."
    ]
    for sample in real_story_samples:
        assert not is_frontmatter_text(sample), f"False positive frontmatter detection: {sample}"
        assert not is_backmatter_text(sample), f"False positive backmatter detection: {sample}"

def test_backmatter_detection():
    backmatter_samples = [
        "ISBN: zero-eight hundred and twelve-fifty-three thousand, two hundred and fifteen-five",
        "ISBN 0-812-53215-5",
        "Cover art by Boris Vallejo",
        "Cover design by Peter Thorpe",
        "West Hartford, Connecticut",
        "The End",
        "Finis",
        "End of the Project Gutenberg EBook of The Dueling Machine, by Benjamin William Bova",
        "A WINTER HELL",
        "It's Labor Day. Your New York vacation is over. But your money and I.D. have been stolen.",
        "Now you are prey to the gangs who emerge from the shadows to, fight for the ruins of Manhattan.",
        "About the Author",
        "Author's Afterword",
        "Author's Afterword The distant past has always been just as exciting to me as the distant future",
        "Historical Note and Acknowledgments",
        "Order books online at www.tor-forge.com"
    ]
    for sample in backmatter_samples:
        assert is_backmatter_text(sample), f"Failed to detect backmatter: {sample}"

def test_sanitize_story_paragraphs():
    # Simulate chapter 1 with leading dedication and copyright
    ch1_raw = [
        "Copyright © nineteen eighty-four by Ben Bova",
        "To Regina, with love and hope for a better tomorrow.",
        "Book One",
        "The glass was cold.",
        "Linc rubbed at it with the heel of his hand."
    ]
    sanitized_ch1 = sanitize_story_paragraphs(ch1_raw, is_first_chapter=True, is_last_chapter=False)
    assert sanitized_ch1 == [
        "Book One",
        "The glass was cold.",
        "Linc rubbed at it with the heel of his hand."
    ]

    # Simulate final chapter with trailing copyright and ISBN
    ch_last_raw = [
        "\"I am now. We will journey out to the stars together, my beloved.\"",
        "I leaned across the table and kissed her lips. My loneliness was ended, at last.",
        "Copyright © nineteen eighty-four by Ben Bova",
        "Cover art by Boris Vallejo",
        "ISBN: zero-eight hundred and twelve-fifty-three thousand, two hundred and fifteen-five"
    ]
    sanitized_last = sanitize_story_paragraphs(ch_last_raw, is_first_chapter=False, is_last_chapter=True)
    assert sanitized_last == [
        "\"I am now. We will journey out to the stars together, my beloved.\"",
        "I leaned across the table and kissed her lips. My loneliness was ended, at last."
    ]

def test_sanitize_title_page_and_epigraphs():
    # Simulate Orion in the Dying Time opening: Author, Title, Dedication, Epigraph, Attribution
    opening_raw = [
        "Ben Bova",
        "Orion in the Dying Time",
        "To Lester del Rey, mentor",
        "\"An intelligence knowing, at a given instance of time, all forces acting in nature...\"",
        "-- Pierre-Simon de Laplace",
        "What if there were more than one such person?",
        "Prologue",
        "With Anya beside me, I walked out of the ancient temple into the warming sunshine of a new day."
    ]
    sanitized = sanitize_story_paragraphs(opening_raw, is_first_chapter=True, book_title="Orion in the Dying Time")
    assert sanitized == [
        "What if there were more than one such person?",
        "Prologue",
        "With Anya beside me, I walked out of the ancient temple into the warming sunshine of a new day."
    ]

def test_epub_spine_order_not_alphabetical():
    # New Earth has chapter1.html, chapter2.html, chapter10.html
    epub_path = "/media/media/14TB/GoogleDriveCTW/Ben Bova/New Earth - Ben Bova.epub"
    if os.path.exists(epub_path):
        story_files = get_epub_spine_story_files(epub_path)
        # Verify that chapter 2 comes before chapter 10 in spine order!
        ch2_idx = -1
        ch10_idx = -1
        for idx, f in enumerate(story_files):
            if "chapter2.html" in f:
                ch2_idx = idx
            elif "chapter10.html" in f:
                ch10_idx = idx
        assert ch2_idx != -1 and ch10_idx != -1
        assert ch2_idx < ch10_idx, f"Chapter 2 ({ch2_idx}) should appear before Chapter 10 ({ch10_idx}) in spine order!"

def test_epub_spine_vengeance_of_orion_purity():
    epub_path = "/media/media/14TB/GoogleDriveCTW/Ben Bova/Vengeance of Orion - Ben Bova.epub"
    if os.path.exists(epub_path):
        story_files = get_epub_spine_story_files(epub_path)
        assert len(story_files) == 49
        assert "VoO_split_002.html" not in story_files, "Dedication VoO_split_002.html should be excluded!"
        assert "VoO_split_055.html" not in story_files, "Afterword VoO_split_055.html should be excluded!"
        assert story_files[0] == "VoO_split_003.html"
        assert story_files[-1] == "VoO_split_054.html"

def test_epub_spine_url_encoded_href():
    epub_path = "/media/media/14TB/books/Dolores Cannon SUPERpak (2)/Dolores Cannon - The Custodians/Dolores Cannon - The Custodians.epub"
    if os.path.exists(epub_path):
        story_files = get_epub_spine_story_files(epub_path)
        assert len(story_files) > 0, "URL-encoded manifest hrefs should be unquoted and discovered!"
        assert any("Chapter 1.xhtml" in f or "Chapter%201.xhtml" in f for f in story_files)

def test_clean_urls_from_text():
    from scripts.pipeline_v3.normalizer import clean_urls_from_text
    sample = (
        "visit the Web sites of the Center for Science in the Public Interest (http://www.cspinet.org); "
        "the Rudd Center at Yale University (http://www.yaleruddcenter.org). "
        "The complete article is available at (http://www.cdc.gov/mmwr/preview/mmwrhtml/rr5807a1.htm). "
        "Support groups on its Web site: //http://www.nationaleatingdisorders.org/get-help-today/."
    )
    cleaned = clean_urls_from_text(sample)
    assert "http" not in cleaned
    assert "www" not in cleaned
    assert "visit the Web sites of the Center for Science in the Public Interest; the Rudd Center at Yale University." in cleaned

    # Test spaced/broken URL & Source website citation
    sample_source = (
        "For a full commentary on the Five Mindfulness Trainings, see For a Future to Be Possible, by Thich Nhat Hanh. "
        "Source: Plum Village Web site, http://www.plum village.org/mindfulness-trainings/3-the-five-mindfulness-trainings.html."
    )
    cleaned_source = clean_urls_from_text(sample_source)
    assert "village.org" not in cleaned_source
    assert "http" not in cleaned_source
    assert cleaned_source == "For a full commentary on the Five Mindfulness Trainings, see For a Future to Be Possible, by Thich Nhat Hanh."

    # Test bare domain reference
    sample_bare = "The government Web site healthfinder.gov has links to several Web sites."
    cleaned_bare = clean_urls_from_text(sample_bare)
    assert "healthfinder.gov" not in cleaned_bare
    assert "Healthfinder" in cleaned_bare

def test_savor_harpercollins_spine_purity():
    epub_path = "/media/media/TOSHIBA EXT/AI/TNHBooks/Nhat_Hanh_Thich_Zen_Buddhist_Master_110_books/Savor/Nhat_Hanh_Thich_Savor_Mindful_Eating_Mindful_Life_HarperCollins_2010.epub"
    if os.path.exists(epub_path):
        story_files = get_epub_spine_story_files(epub_path)
        assert len(story_files) == 9
        assert not any("app" in f.lower() for f in story_files)
        assert not any("ind" in f.lower() for f in story_files)
        assert not any("loi" in f.lower() for f in story_files)
        assert not any("nts" in f.lower() for f in story_files)
        assert not any("frd" in f.lower() for f in story_files)
        assert not any("cop" in f.lower() for f in story_files)

def test_nora_roberts_spine_purity():
    epub_path = "/media/media/12OMVMedia/data/downloads/books/Nora Roberts - Nightshade (retail) (epub)/Nora Roberts - Nightshade (retail) (epub).epub"
    if os.path.exists(epub_path):
        story_files = get_epub_spine_story_files(epub_path)
        assert len(story_files) == 14
        assert not any("abouttheauthor" in f.lower() for f in story_files)
        assert not any("newsletter" in f.lower() for f in story_files)
        assert not any("backmatter" in f.lower() for f in story_files)
        assert not any("seriespage" in f.lower() for f in story_files)
        assert story_files[0].endswith("prologue.xhtml")
        assert story_files[-1].endswith("chapter13.xhtml")


def test_extract_and_reflow_paragraphs():
    from scripts.pipeline_v3.normalizer import extract_and_reflow_paragraphs

    # Simulate line-wrapped OCR EPUB with page numbers and broken lines
    sample_html = """
    <html><body>
    <p class="calibre2">They found themselves back at Vorgens' tent, with its</p>
    <p class="calibre2">quadruple guard.</p>
    <p class="calibre2">&nbsp;</p>
    <p class="calibre2">"You have answered my questions quite frankly," Sittas</p>
    <p class="calibre2">said, "for which I thank you. Now tell me, what questions</p>
    <p class="calibre2">can I answer for you?"</p>
    <p class="calibre2">&nbsp;</p>
    <p class="calibre2">112 Ben Bova</p>
    <p class="calibre2">&nbsp;</p>
    <p class="calibre2">Vorgens smiled thinly. "I have only one question: will</p>
    <p class="calibre2">your people fight?"</p>
    </body></html>
    """
    paras = extract_and_reflow_paragraphs(sample_html, book_title="The Watchmen")
    assert len(paras) == 3
    assert paras[0] == "They found themselves back at Vorgens' tent, with its quadruple guard."
    assert paras[1] == '"You have answered my questions quite frankly," Sittas said, "for which I thank you. Now tell me, what questions can I answer for you?"'
    assert paras[2] == 'Vorgens smiled thinly. "I have only one question: will your people fight?"'
    assert not any("112" in p for p in paras)
    assert not any("Ben Bova" in p for p in paras)


def test_split_into_complete_thoughts_no_awkward_breaks():
    from scripts.pipeline_v3.normalizer import split_into_complete_thoughts

    # 1. Complex sentence with colon, parentheticals, and long clause
    complex_para = (
        "Tipped-off by the Koo-kuh-mon-guh police department, Detective Sgt Jim Willis from the "
        "San Bernardino sheriff's office vice squad auditioned for the part of Senator Gurney "
        "(the 'role of the asshole', as Zappa put it) and was convinced he had uncovered a vice den."
    )
    thoughts = split_into_complete_thoughts(complex_para, max_chars=260)
    assert len(thoughts) == 2
    # Ensure no awkward break splitting 'vice' and 'den'
    assert not any(t.strip() == "den." for t in thoughts)
    assert thoughts[0].endswith("asshole',") or thoughts[0].endswith("put it)")
    assert "vice den." in thoughts[1]

    # 2. Person initials protection: B. B. King should not split across sentences
    initials_para = "He listened to B. B. King and H. L. Mencken before writing his first orchestral piece."
    thoughts_init = split_into_complete_thoughts(initials_para, max_chars=260)
    assert len(thoughts_init) == 1
    assert "King" in thoughts_init[0]
    assert not any(t.strip() == "B." or t.strip() == "King." for t in thoughts_init)


def test_compute_qa_accuracy_autojunk_false_long_thoughts():
    from scripts.pipeline_v3.qa_gate import compute_qa_accuracy

    # Long thought (>200 chars) with a single-word name variant at the end
    target = (
        "McNab's already processing the husband's 'link. The upshot is she was snatched by person "
        "or persons unknown for reasons as yet undetermined. But it wasn't random, it wasn't a mugging, "
        "and there's no evidence at this early stage to indicate Judge Yung is connected to that reason."
    )
    # Whisper commonly transcribes Yung as Young
    transcription = target.replace("Yung", "Young")

    acc = compute_qa_accuracy(target, transcription)
    # Must maintain > 95% accuracy and not drop to 88% due to difflib autojunk truncation
    assert acc >= 0.95
    assert acc >= 0.98


def test_megre_ringing_cedars_pure_story_extraction():
    from scripts.pipeline_v3.epub_parser import extract_pure_story_chapters_from_epub

    epub_path = "/media/media/14TB/Library/Vladimir Megre - The Ringing Cedars of Russia 1-10 (Anastasia)/Vladimir Megre - Ringing Cedars 03 - The Dimension of Love.epub"
    if os.path.exists(epub_path):
        chapters = extract_pure_story_chapters_from_epub(epub_path)
        # Must resolve all 24 narrative chapters instead of collapsing into 1 chapter
        assert len(chapters) == 24
        # First chapter must be Chapter 01 "ANOTHER PILGRIM" (not title page / publisher dump)
        assert "ANOTHER PILGRIM" in chapters[0]["paragraphs"][0].upper()
        # Last chapter must not end with author appeal or website contact dump
        last_para = chapters[-1]["paragraphs"][-1]
        assert "www." not in last_para
        assert "PO Box" not in last_para
        assert "appeal from" not in last_para.lower()


def test_megre_ringing_cedars_books6_10_pure_story_extraction():
    from scripts.pipeline_v3.epub_parser import extract_pure_story_chapters_from_epub

    base_dir = "/media/media/14TB/Library/Vladimir Megre - The Ringing Cedars of Russia 1-10 (Anastasia)"
    
    # Test Book 10 (Anasta) - must have exactly 35 narrative chapters, ending with 'Your papa' without Translator's Notes
    p10 = os.path.join(base_dir, "Vladimir Megre - Ringing Cedars 10 - Anasta.epub")
    if os.path.exists(p10):
        ch10 = extract_pure_story_chapters_from_epub(p10)
        assert len(ch10) == 35
        assert "ANASTA" in ch10[0]["paragraphs"][0].upper()
        assert ch10[-1]["paragraphs"][-1].strip() == "Your papa"
        assert not any("translator" in p.lower() for p in ch10[-1]["paragraphs"])

    # Test Book 7 (The Energy of Life) - must have exactly 27 narrative chapters without author note to readers
    p7 = os.path.join(base_dir, "Vladimir Megre - Ringing Cedars 07 - The Energy of Life.epub")
    if os.path.exists(p7):
        ch7 = extract_pure_story_chapters_from_epub(p7)
        assert len(ch7) == 27
        assert "CREATIVE THOUGHT" in ch7[0]["paragraphs"][0].upper()
        assert "ENERGY OF LIFE" in ch7[-1]["paragraphs"][-1].upper()
        assert not any("to the readers" in c["chapter_title"].lower() for c in ch7)


def test_expanse_core_trilogy_pure_story_extraction():
    from scripts.pipeline_v3.epub_parser import extract_pure_story_chapters_from_epub

    base_dir = "/media/media/14TB/Library/James S. A. Corey - The Expanse Complete - Jefferson Mays"

    # Test Caliban's War - must start with Prologue: Mei, not "BY JAMES S. A. COREY"
    p_cw = os.path.join(base_dir, "Corey, James S. A. - The Expanse 2.0 - Caliban's War", "Corey, James S. A. - The Expanse 2.0 - Caliban's War.epub")
    if os.path.exists(p_cw):
        ch_cw = extract_pure_story_chapters_from_epub(p_cw)
        assert len(ch_cw) == 56
        assert ch_cw[0]["chapter_title"].startswith("Prologue: Mei")
        assert not any("by james s. a. corey" in p.lower() for p in ch_cw[0]["paragraphs"][:3])

    # Test Abaddon's Gate - must start with Prologue: Manéo, not "B Y J AMES S. A. C OREY"
    p_ag = os.path.join(base_dir, "Corey, James S. A. - The Expanse 3.0 - Abaddon's Gate", "Corey, James S. A. - The Expanse 3.0 - Abaddon's Gate.epub")
    if os.path.exists(p_ag):
        ch_ag = extract_pure_story_chapters_from_epub(p_ag)
        assert len(ch_ag) == 55
        assert ch_ag[0]["chapter_title"].startswith("Prologue: Manéo")
        assert not any("copyright" in p.lower() for p in ch_ag[0]["paragraphs"][:3])


def test_qa_accuracy_phonetic_and_compound_invariance():
    from scripts.pipeline_v3.qa_gate import compute_qa_accuracy

    # 1. Honorifics + proper noun homophones (Mr -> Mister, Stuart -> Stewart, Kerry -> Carrie)
    t1 = (
        "She lifted one slim eyebrow, the gesture as deliberate as his own. Mr Donnelly. "
        "Oh, thank you, Chad. She accepted the glass of champagne, touched a hand briefly "
        "to the arm of the man who'd brought it to her. Chad Stuart, Brian Donnelly, from Kerry."
    )
    a1 = (
        "She lifted one slim eyebrow, the gesture as deliberate as his own. Mister Donnelly. "
        "Oh, thank you, Chad. She accepted the glass of champagne, touched a hand briefly "
        "to the arm of the man who'd brought it to her. Chad Stewart, Brian Donnelly, from Carrie."
    )
    assert compute_qa_accuracy(t1, a1) >= 0.98

    # 2. Compound word whitespace + US/UK spelling (realized/realised, overwarm/over warm, overcrowded/over crowded)
    t2 = "Which was where she wanted to be right now, she realized. Home. The thought of going back inside that overwarm and overcrowded room seemed unbearable."
    a2 = "Which was where she wanted to be right now, she realised. Home. The thought of going back inside that over warm and over crowded room seemed unbearable."
    assert compute_qa_accuracy(t2, a2) >= 0.99

    # 3. True dropcap split ("T he") MUST NOT be merged and must still be penalized
    t3 = "The glass was cold in his hand."
    a3 = "T he glass was cold in his hand."
    assert compute_qa_accuracy(t3, a3) < 0.90


def test_normalizer_mac_roman_and_navbar_cleanup():
    from scripts.pipeline_v3.normalizer import clean_html_and_text

    raw = '<p>Contents - Prev | Next "Becausec" she saidc, looking at theRacing form. It was socexotic.</p>'
    cleaned = clean_html_and_text(raw)
    assert "Prev | Next" not in cleaned
    assert "Because..." in cleaned
    assert "said..." in cleaned
    assert "the Racing" in cleaned
    assert "so... exotic" in cleaned


def test_uniform_48k_and_chapter_indexed_master_packaging(tmp_path):
    import subprocess
    from mutagen.mp3 import MP3
    from mutagen.id3 import ID3
    from scripts.pipeline_v3.packager import generate_master_package

    ch_dir = tmp_path / "chapters"
    ch_dir.mkdir()
    ch1 = str(ch_dir / "01_Chapter_01.mp3")
    ch2 = str(ch_dir / "02_Chapter_02.mp3")

    # Create one 24kHz chapter and one 48kHz chapter to simulate mixed loudnorm output
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "0.5", "-c:a", "libmp3lame", "-b:a", "192k", "-ar", "24000", ch1], check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono", "-t", "0.5", "-c:a", "libmp3lame", "-b:a", "192k", "-ar", "48000", ch2], check=True)

    master_out = str(tmp_path / "Test_Book_Full_Audiobook.mp3")
    generate_master_package(
        out_dir=str(tmp_path),
        master_name="Test_Book_Full_Audiobook.mp3",
        book_title="Test Book",
        author="Test Author",
        rendered_chapter_mp3s=[ch1, ch2],
        chapter_timestamps=[("00:00:00", "Chapter 01", "01_Chapter_01.mp3"), ("00:00:01", "Chapter 02", "02_Chapter_02.mp3")],
    )

    # 1. Both chapters and the master must now be 48,000 Hz
    assert MP3(ch1).info.sample_rate == 48000
    assert MP3(ch2).info.sample_rate == 48000
    assert MP3(master_out).info.sample_rate == 48000

    # 2. Master MP3 must contain native ID3v2 CTOC and CHAP chapter index frames
    id3 = ID3(master_out)
    assert len(id3.getall("CTOC")) == 1
    assert len(id3.getall("CHAP")) == 2

    # 3. playlist.m3u and playlist_absolute.m3u must reference only the single *_Full_Audiobook.mp3 master
    abs_lines = [l.strip() for l in (tmp_path / "playlist_absolute.m3u").read_text().splitlines() if l.strip() and not l.startswith("#")]
    assert abs_lines == [master_out]
    assert not any("/chapters/" in l for l in abs_lines)


def test_no_script_encodes_mp3_without_48k():
    import re
    scripts_root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts")
    offenders = []
    for dp, _, filenames in os.walk(scripts_root):
        for fn in filenames:
            if fn.endswith(".py"):
                p = os.path.join(dp, fn)
                txt = open(p, encoding="utf-8", errors="ignore").read()
                for m in re.finditer(r"libmp3lame", txt):
                    window = txt[max(0, m.start() - 150):min(len(txt), m.end() + 200)]
                    if "48000" not in window:
                        offenders.append(os.path.relpath(p, scripts_root))
    assert offenders == [], f"Scripts with libmp3lame missing -ar 48000: {offenders}"



