"""
OmniVoice Studio Pipeline v3.0 Master Package
"""

from .normalizer import (
    clean_html_and_text,
    extract_and_reflow_paragraphs,
    split_into_complete_thoughts,
    normalize_numbers_and_currency,
    balance_dialogue_quotes,
    mend_hyphenated_linebreaks,
    mend_dropcap_and_inline_splits,
    apply_expanse_phonetics,
    EXPANSE_PHONETIC_REPLACEMENTS,
    apply_ringing_cedars_phonetics,
    RINGING_CEDARS_PHONETIC_REPLACEMENTS,
    PreflightHTMLParser
)
from .qa_gate import (
    normalize_qa_tokens,
    compute_qa_accuracy,
    query_crisperwhisper_qa
)
from .dsp import (
    apply_zero_crossing_fades,
    assemble_chapter_audio,
    encode_chapter_mp3
)
from .packager import (
    extract_cover_image,
    embed_id3_cover_art,
    format_timestamp,
    generate_master_package
)
from .async_engine import (
    create_pooled_session,
    synthesize_thought_chunk_sync,
    process_chapter_pipelined
)
from .pure_story_checker import (
    is_frontmatter_text,
    is_backmatter_text,
    sanitize_story_paragraphs,
    get_epub_spine_story_files,
    verify_book_qa_reports,
    preflight_audit_book_epub,
    validate_manifest_formatting_integrity
)
from .auk_repair import (
    build_repair_instruction,
    query_auk_repair,
    repair_and_verify_chunk
)
from .cluster_nodes import (
    NODES,
    resolve_node_endpoints
)
from .epub_parser import (
    extract_clean_paragraphs_from_html,
    extract_pure_story_chapters_from_epub
)

__all__ = [
    "build_repair_instruction",
    "query_auk_repair",
    "repair_and_verify_chunk",
    "NODES",
    "resolve_node_endpoints",

    "clean_html_and_text",
    "extract_and_reflow_paragraphs",
    "split_into_complete_thoughts",
    "normalize_numbers_and_currency",
    "balance_dialogue_quotes",
    "mend_hyphenated_linebreaks",
    "mend_dropcap_and_inline_splits",
    "apply_expanse_phonetics",
    "EXPANSE_PHONETIC_REPLACEMENTS",
    "PreflightHTMLParser",
    "normalize_qa_tokens",
    "compute_qa_accuracy",
    "query_crisperwhisper_qa",
    "apply_zero_crossing_fades",
    "assemble_chapter_audio",
    "encode_chapter_mp3",
    "extract_cover_image",
    "embed_id3_cover_art",
    "format_timestamp",
    "generate_master_package",
    "create_pooled_session",
    "synthesize_thought_chunk_sync",
    "process_chapter_pipelined",
    "is_frontmatter_text",
    "is_backmatter_text",
    "sanitize_story_paragraphs",
    "get_epub_spine_story_files",
    "verify_book_qa_reports",
    "preflight_audit_book_epub",
    "validate_manifest_formatting_integrity",
    "extract_clean_paragraphs_from_html",
    "extract_pure_story_chapters_from_epub"
]
