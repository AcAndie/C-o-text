"""Xử lý đầu vào file cục bộ (EPUB và TXT) với luồng hợp nhất (Task 6.1)."""
from __future__ import annotations

from cao_text.files.epub import extract_story_name_from_epub, read_epub_documents
from cao_text.files.flow import detect_input_type, run_file_flow
from cao_text.files.txt import extract_story_name_from_txt, read_txt_documents
from cao_text.models import FileSpec, RawDocument

__all__ = [
    "FileSpec",
    "RawDocument",
    "detect_input_type",
    "extract_story_name_from_epub",
    "extract_story_name_from_txt",
    "read_epub_documents",
    "read_txt_documents",
    "run_file_flow",
]
