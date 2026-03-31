# ai/prompts.py
"""
ai/prompts.py — Quản lý tập trung tất cả prompt gửi Gemini.

Tại sao cần file này:
  - Khi có >6 agent function, prompt nằm rải rác trong code Python rất khó
    tinh chỉnh và A/B test.
  - Tách prompt ra đây giúp: version-control riêng, dễ đọc, dễ sửa mà
    không phải đụng vào logic Python.
  - Mỗi prompt là 1 classmethod của PromptTemplates → IDE auto-complete,
    dễ tìm kiếm, không typo key string.

Quy ước:
  - Mỗi hàm nhận các tham số cần thiết, trả về str (prompt hoàn chỉnh).
  - Không import gì từ project nội bộ → tránh circular import.
  - Tất cả prompt dùng tiếng Việt cho instruction, tiếng Anh cho JSON schema
    (Gemini hiểu JSON schema tiếng Anh tốt hơn).
"""
from __future__ import annotations


class PromptTemplates:
    """
    Namespace tập trung cho toàn bộ prompt gửi Gemini.

    Dùng như: PromptTemplates.build_profile(html, url)
    """

    # ── Site profile ──────────────────────────────────────────────────────────

    @staticmethod
    def build_profile(html_snippet: str, url: str) -> str:
        return f"""Phân tích HTML trang chương truyện sau và trả về JSON.
URL: {url}

HTML (rút gọn, tối đa 8000 ký tự):
{html_snippet}

Yêu cầu JSON (CHỈ JSON, không có text khác, không markdown fence):
{{
  "next_selector": "CSS selector tìm nút/link sang chương tiếp theo",
  "title_selector": "CSS selector tìm tiêu đề chương",
  "content_selector": "CSS selector vùng nội dung chính (KHÔNG phải <body>)"
}}

Quy tắc bắt buộc:
- Selector phải là CSS hợp lệ với BeautifulSoup select_one()
- Ưu tiên #id > .class cụ thể > tag[attribute]
- content_selector PHẢI chứa nội dung truyện, KHÔNG được là body/html/main chung chung
- Trả về null cho field nào không tìm được
- Kiểm tra kỹ: nếu element chứa <script> tags, selector đó KHÔNG hợp lệ
"""

    # ── Story ID guard ────────────────────────────────────────────────────────

    @staticmethod
    def story_id(url_sample: str) -> str:
        return f"""Phân tích các URL chương truyện sau và tìm story ID.

URLs:
{url_sample}

Tìm phần CỐ ĐỊNH trong URL (story_id) và phần THAY ĐỔI (số chương).
Trả về JSON (CHỈ JSON, không markdown fence):
{{
  "story_id": "phần cố định nhận dạng truyện này",
  "story_id_regex": "regex Python để match URL hợp lệ của truyện này"
}}
"""

    # ── Cross-story confirmation ──────────────────────────────────────────────

    @staticmethod
    def confirm_same_story(title1: str, url1: str, title2: str, url2: str) -> str:
        return f"""Hai chương này có thuộc cùng một truyện không?

Chương 1: Tiêu đề: {title1!r} | URL: {url1}
Chương 2: Tiêu đề: {title2!r} | URL: {url2}

Trả về JSON (CHỈ JSON, không markdown fence):
{{"same_story": true, "reason": "lý do ngắn gọn"}}
hoặc
{{"same_story": false, "reason": "lý do ngắn gọn"}}

Chú ý: chỉ trả false nếu rõ ràng là truyện KHÁC (khác domain nghĩa, khác tên truyện).
Nếu không chắc, mặc định trả true.
"""

    # ── First chapter finder ──────────────────────────────────────────────────

    @staticmethod
    def find_first_chapter(candidates: str, base_url: str) -> str:
        return f"""Đây là các URL candidate cho chương đầu tiên của truyện:
{candidates}

Trang nguồn: {base_url}

Trả về JSON (CHỈ JSON, không markdown fence):
{{"first_chapter_url": "URL chương đầu tiên (số nhỏ nhất / đầu tiên trong list)"}}
"""

    # ── Page classifier + next URL ────────────────────────────────────────────

    @staticmethod
    def classify_and_find(hint_block: str, html_snippet: str, base_url: str) -> str:
        return f"""Phân loại trang web và tìm URL chương tiếp theo.

URL hiện tại: {base_url}

Link điều hướng tìm thấy:
{hint_block}

HTML (rút gọn, tối đa 6000 ký tự):
{html_snippet}

Trả về JSON (CHỈ JSON, không markdown fence):
{{
  "page_type": "chapter",
  "next_url": "URL chương tiếp theo hoặc null",
  "first_chapter_url": null
}}
hoặc nếu là trang index:
{{
  "page_type": "index",
  "next_url": null,
  "first_chapter_url": "URL chương đầu tiên"
}}
"""

    # ── Title validation ──────────────────────────────────────────────────────

    @staticmethod
    def validate_title(candidate: str, chapter_url: str, content_snippet: str) -> str:
        return f"""Xác nhận tiêu đề chương truyện.

URL: {chapter_url}
Tiêu đề đề xuất: {candidate!r}
Đoạn đầu nội dung trang (300 ký tự): {content_snippet[:300]!r}

Tiêu đề trên có hợp lệ không? Nếu có, trả về tiêu đề đã làm sạch.
Trả về JSON (CHỈ JSON, không markdown fence):
{{"valid": true, "title": "tiêu đề làm sạch"}}
hoặc
{{"valid": false, "title": null}}
"""

    # ── Ads detection ─────────────────────────────────────────────────────────

    @staticmethod
    def detect_ads(context_text: str) -> str:
        return f"""You are a text filter assistant for web novel scrapers.

Below are suspicious lines found in novel chapters. Each entry shows:
- Up to 10 lines of context BEFORE the suspicious line
- The suspicious line itself (marked with >>> <<<)
- Up to 10 lines of context AFTER the suspicious line

Use the surrounding context to judge whether the marked line is truly
an injected watermark/ad, or just normal story content that happened
to match a keyword.

IMPORTANT: A line is only ads/watermark if it is clearly injected by an
aggregator site and does NOT belong to the story's narrative. If the
surrounding context shows it is part of the story (e.g. a character
mentions Amazon, a site name, or copyright as part of the plot, skill name, etc.),
mark it as NOT ads.

SUSPICIOUS LINES WITH CONTEXT:
{context_text}

Return ONLY a JSON object, no markdown, no extra text:
{{
  "found": true,
  "keywords": ["short phrases to add to keyword list, lowercase, max 8"],
  "patterns": ["python regex patterns, case-insensitive, max 5"],
  "example_lines": ["exact text of the >>> marked lines <<< that ARE ads, verbatim, max 5"]
}}

If none of the marked lines are ads, return:
{{"found": false, "keywords": [], "patterns": [], "example_lines": []}}"""