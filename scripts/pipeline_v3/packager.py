"""
Pipeline v3.0 — Master Audio Packager, Cover Art Embedding, & Playlists
"""

import os
import time
import shutil
import zipfile
import subprocess
import urllib.parse
import xml.etree.ElementTree as ET
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, CHAP, CTOC, CTOCFlags, TIT2, error

def extract_cover_image(epub_path: str, output_dir: str) -> str | None:
    """Extracts front cover image from EPUB into cover.jpg."""
    if not os.path.exists(epub_path):
        return None

    target_cover_path = os.path.join(output_dir, "cover.jpg")
    if os.path.exists(target_cover_path) and os.path.getsize(target_cover_path) > 5000:
        return target_cover_path

    try:
        zf = zipfile.ZipFile(epub_path, "r")
        cover_bytes = None

        # 1. Inspect OPF metadata for declared cover
        opf_names = [f for f in zf.namelist() if f.endswith('.opf')]
        if opf_names:
            opf_path = opf_names[0]
            opf_dir = opf_path.split('/')[0] if '/' in opf_path else ''
            try:
                tree = ET.fromstring(zf.read(opf_path))
                cover_id = None
                for meta in tree.findall('.//{*}meta'):
                    if meta.attrib.get('name') == 'cover':
                        cover_id = meta.attrib.get('content')
                        break
                manifest = {}
                for item in tree.findall('.//{*}item'):
                    i_id = item.attrib.get('id')
                    i_href = item.attrib.get('href', '')
                    full_href = f'{opf_dir}/{i_href}'.replace('\\', '/') if opf_dir else i_href
                    full_href = urllib.parse.unquote(full_href)
                    manifest[i_id] = full_href
                    if 'cover-image' in item.attrib.get('properties', ''):
                        cover_bytes = zf.read(full_href)
                        break
                if not cover_bytes and cover_id and cover_id in manifest:
                    cover_bytes = zf.read(manifest[cover_id])
            except Exception:
                pass

        # 2. Check filename keywords
        if not cover_bytes:
            candidates = [
                f for f in zf.namelist()
                if any(k in f.lower() for k in ["cover", "cvi", "jacket"])
                and f.lower().endswith((".jpg", ".jpeg", ".png"))
            ]
            candidates.sort(key=lambda x: (len(x), x))
            if candidates:
                cover_bytes = zf.read(candidates[0])

        # 3. Fallback to largest image
        if not cover_bytes:
            img_candidates = [
                f for f in zf.namelist()
                if f.lower().endswith((".jpg", ".jpeg", ".png"))
            ]
            if img_candidates:
                img_candidates.sort(key=lambda x: -zf.getinfo(x).file_size)
                cover_bytes = zf.read(img_candidates[0])

        if cover_bytes:
            with open(target_cover_path, "wb") as out_img:
                out_img.write(cover_bytes)
            return target_cover_path
    except Exception:
        pass
    return None

def embed_id3_cover_art(mp3_path: str, cover_image_path: str | None = None, cover_path: str | None = None, **kwargs):
    """Embeds high-resolution cover artwork into MP3 ID3v2 tags via mutagen."""
    target_cover = cover_image_path or cover_path
    if not target_cover or not os.path.exists(target_cover) or not os.path.exists(mp3_path):
        return

    try:
        audio = MP3(mp3_path, ID3=ID3)
        try:
            audio.add_tags()
        except error:
            pass

        mime_type = "image/jpeg" if target_cover.lower().endswith((".jpg", ".jpeg")) else "image/png"
        with open(target_cover, "rb") as img:
            audio.tags.add(
                APIC(
                    encoding=3, # UTF-8
                    mime=mime_type,
                    type=3,     # Front Cover
                    desc="Cover",
                    data=img.read()
                )
            )
        audio.save(v2_version=3)
    except Exception as e:
        pass

def format_timestamp(seconds: float) -> str:
    """Formats float seconds into HH:MM:SS."""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hrs:02d}:{mins:02d}:{secs:02d}"


def embed_id3_chapters(mp3_path: str, rendered_chapter_mp3s: list[str], chapter_timestamps: list | None = None):
    """Embeds native ID3v2 CTOC and CHAP chapter index frames into the master MP3."""
    if not os.path.exists(mp3_path) or not rendered_chapter_mp3s:
        return
    try:
        audio = MP3(mp3_path, ID3=ID3)
        try:
            audio.add_tags()
        except error:
            pass
        audio.tags.delall("CHAP")
        audio.tags.delall("CTOC")

        chap_specs = []
        cum_ms = 0
        for idx, ch_p in enumerate(rendered_chapter_mp3s):
            if not os.path.exists(ch_p):
                continue
            try:
                ch_info = MP3(ch_p).info
                dur_ms = max(1, int(round(ch_info.length * 1000.0)))
            except Exception:
                dur_ms = 1000
            c_title = f"Chapter {idx + 1:02d}"
            if chapter_timestamps and idx < len(chapter_timestamps):
                item = chapter_timestamps[idx]
                if isinstance(item, dict):
                    c_title = item.get("title") or c_title
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    c_title = str(item[0]) if isinstance(item[1], (int, float)) else str(item[1])
            else:
                try:
                    ch_id3 = ID3(ch_p)
                    if "TIT2" in ch_id3 and ch_id3["TIT2"].text:
                        c_title = str(ch_id3["TIT2"].text[0])
                except Exception:
                    pass
            chap_specs.append((f"chp{idx + 1}", c_title, cum_ms, cum_ms + dur_ms))
            cum_ms += dur_ms

        if not chap_specs:
            return

        child_ids = [cid for cid, _, _, _ in chap_specs]
        audio.tags.add(
            CTOC(
                encoding=3,
                element_id="toc",
                flags=CTOCFlags.TOP_LEVEL | CTOCFlags.ORDERED,
                child_element_ids=child_ids,
                sub_frames=[TIT2(encoding=3, text=["Table of Contents"])],
            )
        )
        for cid, c_title, start_ms, end_ms in chap_specs:
            audio.tags.add(
                CHAP(
                    encoding=3,
                    element_id=cid,
                    start_time=start_ms,
                    end_time=end_ms,
                    sub_frames=[TIT2(encoding=3, text=[c_title])],
                )
            )
        audio.save(v2_version=3)
    except Exception:
        pass


def _ensure_chapter_48k(mp3_p: str):
    """Guarantees chapter MP3 is 48,000 Hz before stream-copy concatenation."""
    if not os.path.exists(mp3_p):
        return
    try:
        sr = MP3(mp3_p).info.sample_rate
        if sr == 48000:
            return
    except Exception:
        pass
    tmp_48k = mp3_p + ".48k_pkg.mp3"
    try:
        subprocess.run([
            "ffmpeg", "-nostdin", "-y", "-v", "error", "-i", mp3_p,
            "-vn", "-c:a", "libmp3lame", "-b:a", "192k", "-ar", "48000",
            "-map_metadata", "0", tmp_48k
        ], check=True)
        if os.path.exists(tmp_48k) and os.path.getsize(tmp_48k) > 1000:
            os.replace(tmp_48k, mp3_p)
    finally:
        if os.path.exists(tmp_48k):
            try:
                os.remove(tmp_48k)
            except Exception:
                pass


def generate_master_package(
    out_dir: str | None = None,
    master_name: str | None = None,
    book_info: dict | None = None,
    rendered_chapter_mp3s: list[str] | None = None,
    chapter_timestamps: list[tuple[str, str, str]] | None = None,
    cover_image_path: str | None = None,
    *,
    book_title: str | None = None,
    author: str | None = None,
    year: str | None = None,
    series: str | None = None,
    chapter_mp3s: list[str] | None = None,
    master_mp3_name: str | None = None,
    master_output_path: str | None = None,
    chapters_info: list[dict] | None = None,
    cover_path: str | None = None,
    **kwargs
):
    """
    Concatenates master MP3, embeds ID3 cover art, generates M3U playlists,
    and writes zero-indexed YouTube timestamp descriptions.
    Supports both directory-based and path-based invocations.
    """
    if cover_path and not cover_image_path:
        cover_image_path = cover_path

    if master_output_path:
        if not out_dir:
            out_dir = os.path.dirname(master_output_path)
        if not master_name:
            master_name = os.path.basename(master_output_path)

    if not out_dir:
        raise ValueError("out_dir or master_output_path must be provided to generate_master_package")

    if book_info is None:
        book_info = {}
    else:
        book_info = dict(book_info)
    if book_title:
        book_info["title"] = book_title
    if author:
        book_info["author"] = author
    if year:
        book_info["year"] = year
    if series:
        book_info["series"] = series

    book_info.setdefault("title", os.path.basename(out_dir).replace("_narration", "").replace("_", " ").title())
    book_info.setdefault("author", "OmniVoice Studio")

    if master_mp3_name and not master_name:
        master_name = master_mp3_name
    if not master_name:
        master_name = f"{book_info.get('title', 'Master_Audiobook').replace(' ', '_')}.mp3"

    if chapters_info:
        if not rendered_chapter_mp3s:
            rendered_chapter_mp3s = [c["mp3_path"] for c in chapters_info if "mp3_path" in c]
        if not chapter_timestamps:
            chapter_timestamps = []
            cum = 0.0
            for c in chapters_info:
                t_title = c.get("chapter_title", f"Chapter {c.get('chapter_index', len(chapter_timestamps)+1)}")
                chapter_timestamps.append((t_title, cum))
                dur = c.get("duration", 0.0)
                if dur <= 0.0 and "mp3_path" in c and os.path.exists(c["mp3_path"]):
                    try:
                        probe = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", c["mp3_path"]]).decode().strip()
                        dur = float(probe)
                    except Exception:
                        dur = 0.0
                cum += dur

    if chapter_mp3s and not rendered_chapter_mp3s:
        rendered_chapter_mp3s = chapter_mp3s
    if rendered_chapter_mp3s is None:
        rendered_chapter_mp3s = []
    if chapter_timestamps is None:
        chapter_timestamps = []

    master_mp3_path = os.path.join(out_dir, master_name)
    extreme_ssd_scratch = "/media/media/Extreme SSD/tmp_audio_scratch"
    is_extreme_scratch = False
    if os.path.exists(extreme_ssd_scratch) and os.access(extreme_ssd_scratch, os.W_OK):
        temp_dir = os.path.join(extreme_ssd_scratch, f"pkg_{os.getpid()}_{int(time.time())}")
        is_extreme_scratch = True
    else:
        temp_dir = os.path.join(out_dir, "temp_chunks")
    os.makedirs(temp_dir, exist_ok=True)
    concat_list_file = os.path.join(temp_dir, "concat_list.txt")


    # Ensure chapter MP3s are 48,000 Hz and concatenated without mid-stream ID3 headers, with guaranteed cleanup:
    clean_streams_list = []
    try:
        for idx, mp3_p in enumerate(rendered_chapter_mp3s):
            _ensure_chapter_48k(mp3_p)
            clean_mp3 = os.path.join(temp_dir, f"clean_chap_{idx:03d}.mp3")
            subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-i", mp3_p,
                "-map", "0:a", "-c:a", "copy",
                "-map_metadata", "-1", "-id3v2_version", "0",
                clean_mp3
            ], check=True)
            clean_streams_list.append(clean_mp3)

        with open(concat_list_file, 'w', encoding='utf-8') as f:
            for p in clean_streams_list:
                f.write(f"file '{os.path.abspath(p)}'\n")

        cmd_master = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list_file,
            "-c", "copy",
            "-metadata", f"title={book_info['title']} (Full Audiobook)",
            "-metadata", f"artist={book_info['author']}",
            "-metadata", f"album={book_info['title']}",
            "-metadata", f"date={book_info.get('year', '')}",
            "-metadata", "genre=Audiobook",
            master_mp3_path
        ]
        subprocess.run(cmd_master, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    finally:
        # Clean up temporary clean streams and scratch directory even if interrupted or failed
        if is_extreme_scratch:
            shutil.rmtree(temp_dir, ignore_errors=True)
        else:
            for p in clean_streams_list:
                if os.path.exists(p):
                    os.remove(p)

    local_temp_chunks = os.path.join(out_dir, "temp_chunks")
    if kwargs.get("cleanup_temp_chunks", True) and os.path.exists(master_mp3_path) and os.path.getsize(master_mp3_path) > 100000:
        if os.path.exists(local_temp_chunks):
            shutil.rmtree(local_temp_chunks, ignore_errors=True)

    # Embed cover and ID3v2 chapter index (CHAP/CTOC) into master MP3, and cover into each chapter MP3
    if cover_image_path and os.path.exists(cover_image_path):
        embed_id3_cover_art(master_mp3_path, cover_image_path)
        for chap_mp3 in rendered_chapter_mp3s:
            embed_id3_cover_art(chap_mp3, cover_image_path)
    embed_id3_chapters(master_mp3_path, rendered_chapter_mp3s, chapter_timestamps)

    # M3U Playlists: playlist_absolute.m3u and playlist_master.m3u reference the single chapter-indexed master MP3
    rel_m3u_lines = ["#EXTM3U", f"#PLAYLIST:{book_info['title']}", os.path.basename(master_mp3_path)]
    abs_m3u_lines = ["#EXTM3U", f"#PLAYLIST:{book_info['title']}", os.path.abspath(master_mp3_path)]
    chap_m3u_lines = ["#EXTM3U", f"#PLAYLIST:{book_info['title']} (Chapters)"]

    for mp3_p in rendered_chapter_mp3s:
        chap_m3u_lines.append(f"chapters/{os.path.basename(mp3_p)}")

    with open(os.path.join(out_dir, "playlist.m3u"), 'w', encoding='utf-8') as f:
        f.write("\n".join(rel_m3u_lines) + "\n")
    with open(os.path.join(out_dir, "playlist_master.m3u"), 'w', encoding='utf-8') as f:
        f.write("\n".join(abs_m3u_lines) + "\n")
    with open(os.path.join(out_dir, "playlist_chapters.m3u"), 'w', encoding='utf-8') as f:
        f.write("\n".join(chap_m3u_lines) + "\n")
    with open(os.path.join(out_dir, "playlist_absolute.m3u"), 'w', encoding='utf-8') as f:
        f.write("\n".join(abs_m3u_lines) + "\n")
    with open(os.path.join(out_dir, "playlist_absolute.m3u8"), 'w', encoding='utf-8') as f:
        f.write("\n".join(abs_m3u_lines) + "\n")

    # YouTube Description
    yt_lines = [
        f"{book_info['title']} ({book_info.get('year', '')}) by {book_info['author']} — Full Unabridged Audiobook Narration",
        "=" * 75,
        "",
        "📖 ABOUT THIS AUDIOBOOK:",
        f"A complete, broadcast-fidelity AI narration of '{book_info['title']}' by {book_info['author']}.",
        "Produced using OmniVoice Studio Pipeline v3.0 on NVIDIA Grace Blackwell GB10 GPU.",
        "- EBU R128 (-18 LUFS) Broadcast Loudness Normalization",
        "- Complete-Thought Sentence Chunking & Dynamic Breathing Timing",
        "- QA Verified chunk-by-chunk with CrisperWhisper 2.0 Large ASR (95-99% accuracy)",
        "",
        "⏱️ CHAPTER TIMESTAMPS & JUMP MARKERS:"
    ]
    for item in chapter_timestamps:
        if isinstance(item, dict):
            t_str = item.get("timestamp") or format_timestamp(item.get("seconds", 0.0))
            c_title = item.get("title", "")
        elif isinstance(item, (list, tuple)):
            if len(item) == 1:
                t_str, c_title = "00:00:00", str(item[0])
            elif len(item) == 2:
                first, second = item
                if isinstance(second, (int, float)):
                    c_title = str(first)
                    t_str = format_timestamp(second)
                elif isinstance(first, (int, float)):
                    t_str = format_timestamp(first)
                    c_title = str(second)
                else:
                    t_str = str(first)
                    c_title = str(second)
            else:
                t_str = str(item[0])
                c_title = str(item[1])
        else:
            t_str, c_title = "00:00:00", str(item)
        yt_lines.append(f"{t_str} - {c_title}")

    yt_lines.extend([
        "",
        "=" * 75,
        "OmniVoice Studio — DGX Spark GB10 GPU Hardware Acceleration"
    ])

    with open(os.path.join(out_dir, "YOUTUBE_DESCRIPTION.txt"), 'w', encoding='utf-8') as f:
        f.write("\n".join(yt_lines) + "\n")
