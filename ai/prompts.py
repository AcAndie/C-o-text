# ai/prompts.py
"""
ai/prompts.py — Quản lý tập trung tất cả prompt gửi Gemini.

CHANGES (v2):
  build_profile(): Prompt mở rộng — AI giờ trả về 7 field thay vì 3:
    - has_chapter_dropdown, has_rel_next: behavior flags
    - chapter_url_pattern: regex pattern
    - site_notes: ghi chú đặc điểm site
"""
from __future__ import annotations


class PromptTemplates:

    # ── Site profile (EXPANDED) ───────────────────────────────────────────────

    @staticmethod
    def build_profile(html_snippet: str, url: str) -> str:
        return f"""Phân tích HTML trang chương truyện và trả về JSON mô tả cấu trúc site.
URL: {url}

HTML (rút gọn, tối đa 8000 ký tự):
{html_snippet}

Yêu cầu JSON (CHỈ JSON, không có text khác, không markdown fence):
{{
  "next_selector": "CSS selector tìm nút/link sang chương tiếp theo, hoặc null",
  "title_selector": "CSS selector tìm tiêu đề chương, hoặc null",
  "content_selector": "CSS selector vùng nội dung chính, hoặc null",
  "has_chapter_dropdown": true,
  "has_rel_next": false,
  "chapter_url_pattern": "regex Python nhận diện URL chapter, hoặc null",
  "site_notes": "ghi chú ngắn về đặc điểm site, hoặc null"
}}

Quy tắc:
- next_selector: ưu tiên nút "Next Chapter" / nút điều hướng chương tiếp
- content_selector: PHẢI chứa nội dung truyện, KHÔNG được là body/html/main
  Ưu tiên #id > .class cụ thể > tag[attribute]
- has_chapter_dropdown: true nếu có <select> chọn chapter (ví dụ fanfiction.net)
- has_rel_next: true nếu có <link rel="next" href="..."> trỏ đến chapter kế tiếp
- chapter_url_pattern: regex Python (không flags), ví dụ:
    fanfiction.net → "/s/\\\\d+/\\\\d+"
    royalroad      → "/fiction/\\\\d+/[^/]+"
    Trả null nếu không đủ thông tin
- site_notes: ghi chú JS-heavy, paywall, watermark pattern, v.v. Trả null nếu không có
- Trả null cho field không tìm được, KHÔNG bịa
- Nếu element chứa <script>, selector đó KHÔNG hợp lệ
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

Chú ý: chỉ trả false nếu rõ ràng là truyện KHÁC. Nếu không chắc, mặc định trả true.
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

    def classify_and_find(hint_block: str, html_snippet: str, base_url: str, domain_context: str | None = None) -> str:
        prefix = f"Site context: {domain_context}\n\n" if domain_context else ""
        return prefix + f"""Phân loại trang web và tìm URL chương tiếp theo.

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

Trả về JSON (CHỈ JSON, không markdown fence):
{{"valid": true, "title": "tiêu đề làm sạch"}}
hoặc
{{"valid": false, "title": null}}
"""

    # ── Ads detection ─────────────────────────────────────────────────────────

    @staticmethod
    def detect_ads(context_text: str) -> str:
        return f"""You are a text filter assistant for web novel scrapers.

Below are suspicious lines found in novel chapters. Each entry shows context
BEFORE and AFTER the marked line. Use context to judge if the line is truly
an injected watermark/ad (not story content).

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


# ── Profile refinement (v4 NEW) ──────────────────────────────────────────

    @staticmethod
    def refine_profile(observations_summary: str) -> str:
        return f"""Bạn đang review CSS selectors cho một web novel scraper.
Dưới đây là structural signals quan sát được từ nhiều chương của cùng một site:

{observations_summary}

Nhiệm vụ: Dựa trên observations trên, đề xuất CSS selectors tốt nhất.
Trả về JSON (CHỈ JSON, không markdown fence):
{{
  "content_selector": "CSS selector chứa nội dung chương, hoặc null",
  "content_confidence": 0.0,
  "title_selector": "CSS selector tiêu đề chương, hoặc null",
  "title_confidence": 0.0,
  "next_selector": "CSS selector nút/link Next Chapter, hoặc null",
  "next_confidence": 0.0,
  "notes": "ghi chú ngắn về site structure, hoặc null"
}}

Quy tắc:
- confidence: float 0.0–1.0, phản ánh độ nhất quán trong observations
  • >= 90% chapters có cùng pattern → confidence >= 0.9
  • >= 70% chapters                 → confidence >= 0.7
  • < 50% chapters                  → confidence < 0.5, nên trả null
- Ưu tiên specificity: #id > .single-class > tag.class > tag
- Selector phải trỏ đến element CHỨA content/title, không phải wrapper bên ngoài
- content_selector: phải chứa body text truyện (> 200 ký tự), KHÔNG phải sidebar/header
- next_selector: phải trỏ đến <a> hoặc <button> có href sang chương tiếp
- Nếu current profile đã có selector đang hoạt động tốt (working_content_selector),
  chỉ đề xuất thay thế nếu bạn thấy option tốt hơn rõ ràng (confidence >= 0.9)
- Trả null cho bất kỳ field nào không đủ confidence, đừng bịa
"""