"""
ai/prompts.py — Tập trung tất cả prompts gửi Gemini.

Learning Phase (5 calls):
  1. build_initial_profile   — Học selectors cơ bản từ Chapter 1
  2. validate_selectors      — Xác nhận selectors từ Chapter 2
  3. analyze_special_content — Bảng/toán/ký hiệu từ Chapter 3
  4. analyze_formatting      — System box/spoiler/author note từ Chapter 4
  5. final_crosscheck        — Tổng hợp & confidence score từ Chapter 5

Utility:
  naming_rules        — Xác định story name + chapter naming pattern (1 lần/story)
  find_first_chapter  — Tìm URL Chapter 1 từ trang Index
  classify_and_find   — Phân loại trang + tìm next URL (emergency fallback)
  verify_ads          — Xác nhận dòng text có phải ads/watermark không
"""
from __future__ import annotations


class Prompts:

    @staticmethod
    def naming_rules(raw_titles: list[str], base_url: str) -> str:
        """
        Phân tích raw <title> tags để xác định story name và chapter naming pattern.
        Gọi 1 lần khi bắt đầu scrape story mới.
        """
        numbered = "\n".join(
            f"  {i + 1}. {t!r}"
            for i, t in enumerate(raw_titles)
        )
        return f"""Phân tích các raw <title> tags của {len(raw_titles)} chapters liên tiếp để xác định cách đặt tên file.

URL ví dụ: {base_url}

Raw <title> tag content từ các chapters:
{numbered}

Nhiệm vụ:
1. Tìm TÊN TRUYỆN — phần text xuất hiện nhất quán qua tất cả chapters (không thay đổi)
2. Tìm từ khóa chapter (Chapter / Ch. / Episode / Part / ...)
3. Xác định chapters có subtitle riêng không (phần sau chapter number, ví dụ "Chapter 1 – The Beginning" thì subtitle = "The Beginning")
4. Tìm prefix cần bóc (nếu story name đứng trước "Chapter N" trong title)

Trả về JSON (CHỈ JSON thuần, không markdown):
{{
  "story_name": "Tên truyện đầy đủ và chính xác. Không thêm bớt ký tự.",
  "story_prefix_to_strip": "Phần prefix xuất hiện trước chapter keyword, cần bóc khi tạo tên file. Chuỗi rỗng nếu chapter keyword đứng đầu title.",
  "chapter_keyword": "Từ khóa chapter: Chapter | Ch. | Episode | Ep. | Part | Prologue (lowercase, đúng casing như trong title)",
  "has_chapter_subtitle": false,
  "notes": "Ghi chú ngắn nếu cần. null nếu không."
}}

QUAN TRỌNG — phân biệt subtitle thật vs noise:
  ✓ Subtitle THẬT: "Chapter 1 – The Beginning" → subtitle = "The Beginning"
  ✓ Subtitle THẬT: "Chapter 1: Into the Dark" → subtitle = "Into the Dark"
  ✗ KHÔNG phải subtitle: "Chapter 1, a percy jackson fanfic" → đây là story tag/description
  ✗ KHÔNG phải subtitle: "Chapter 1 | SiteName" → đây là site suffix

Ví dụ 1 — FanFiction.net (prefix, không có subtitle thật):
  Titles: ["My Novel Chapter 1, a crossover fanfic | FanFiction", "My Novel Chapter 2, a crossover | FanFiction"]
  → story_name: "My Novel", prefix: "My Novel", keyword: "Chapter", subtitle: false

Ví dụ 2 — RoyalRoad (không có prefix, có subtitle thật):
  Titles: ["Chapter 1 – A [Rolling Stone] Gathers no Moss | The Wandering Inn | Royal Road",
           "Chapter 2 – Gathering Moss | The Wandering Inn | Royal Road"]
  → story_name: "The Wandering Inn", prefix: "", keyword: "Chapter", subtitle: true

Ví dụ 3 — Story với Episode thay vì Chapter:
  Titles: ["Episode 1 – Pilot | My Web Serial", "Episode 2 – The City | My Web Serial"]
  → story_name: "My Web Serial", prefix: "", keyword: "Episode", subtitle: true
"""

    @staticmethod
    def learning_5_final_crosscheck(html_snippet: str, url: str, accumulated_profile: dict) -> str:
        return f"""Bạn đã phân tích 4 chương trước. Đây là Chapter 5 — hãy cross-check và finalize profile.

URL Chapter 5: {url}
HTML (tối đa 8000 ký tự):
{html_snippet}

Profile hiện tại (tích lũy từ 4 chapter trước):
{_format_profile_summary(accumulated_profile)}

Nhiệm vụ:
1. Xác nhận content_selector/next_selector/title_selector có hoạt động trên Chapter 5 không
2. Nếu cần fix → đưa ra selector final tốt nhất
3. **QUAN TRỌNG**: Scan Chapter 5 tìm **CHỈ watermark/ads cố định** (lặp lại ở HẦUHẾT chapters)
4. Đánh giá confidence tổng thể (0.0–1.0)

Trả về JSON (CHỈ JSON thuần):
{{
  "content_selector_final": "Selector tốt nhất — giữ nguyên hoặc cải thiện. null chỉ khi không tìm được.",
  "next_selector_final": "Selector tốt nhất hoặc null.",
  "title_selector_final": "Selector tốt nhất hoặc null.",
  "remove_selectors_final": ["Danh sách ĐẦYĐỦ các selectors cần remove (tích hợp tất cả từ 5 chương)"],
  "ads_keywords": ["Chỉ watermark/ads CỐ ĐỊNH xuất hiện ≥80% chapters, lowercase. Tối đa 10."],
  "confidence": 0.95,
  "notes": "Tóm tắt ngắn về profile chất lượng và bất kỳ quirk nào của site."
}}

TIÊU CHÍ ADS KEYWORDS (✓ GIỮ vs ✗ LOẠI):

✓ GIỮ LẠI - Watermark cố định:
  • "Tip: You can use left, right keyboard keys..."
  • "If you find any errors, please let us know..."
  • "Read at [site]" / "Visit [site]" / "Find this novel at..."
  • Boilerplate disclaimer của site

✗ LOẠI BỎ - Nội dung truyện:
  • Tên nhân vật, tên skill, plot elements
  • Từ generic: "search", "read", "find", "chapter"
  • Single-chapter/rare entries

confidence rubric:
  0.95–1.0: Tất cả selectors confirmed, nav tốt, content clean
  0.80–0.94: Minor issues
  0.60–0.79: 1-2 vấn đề chưa giải quyết
  < 0.60: Nhiều vấn đề, cần manual review
"""

    @staticmethod
    def learning_1_initial_profile(html_snippet: str, url: str) -> str:
        return f"""Bạn là chuyên gia phân tích cấu trúc web novel site.
Phân tích HTML của Chapter 1 và trích xuất thông tin cấu trúc site.

URL: {url}
HTML (tối đa 10000 ký tự):
{html_snippet}

Trả về JSON (CHỈ JSON thuần, không markdown fence, không comment):
{{
  "content_selector": "CSS selector chứa TOÀN BỘ nội dung truyện. Ưu tiên #id > .class cụ thể. KHÔNG chọn body, html, main, sidebar/nav.",
  "next_selector": "CSS selector của nút/link 'Next Chapter'. Phải là <a> hoặc <button> có href. null nếu không tìm thấy.",
  "title_selector": "CSS selector của tiêu đề CHƯƠNG (không phải tên truyện). null nếu không rõ.",
  "remove_selectors": ["CSS selectors cần XÓA: ads, donation banner, nav đầu/cuối, social share. [] nếu không có."],
  "nav_type": "'selector' | 'rel_next' | 'slug_increment' | 'fanfic' | null",
  "chapter_url_pattern": "Regex Python nhận diện URL chapter. null nếu không đủ thông tin.",
  "requires_playwright": false,
  "notes": "Ghi chú đặc biệt. null nếu không có."
}}
"""

    @staticmethod
    def learning_2_validate(html_snippet: str, url: str, current_selectors: dict) -> str:
        return f"""Xác nhận CSS selectors đã học từ Chapter 1 có hoạt động đúng trên Chapter 2 không.

URL Chapter 2: {url}
Selectors cần xác nhận:
  content_selector: {current_selectors.get('content_selector')!r}
  next_selector:    {current_selectors.get('next_selector')!r}
  title_selector:   {current_selectors.get('title_selector')!r}
  remove_selectors: {current_selectors.get('remove_selectors', [])}

HTML Chapter 2 (tối đa 8000 ký tự):
{html_snippet}

Trả về JSON (CHỈ JSON thuần):
{{
  "content_valid": true,
  "content_fix": null,
  "next_valid": true,
  "next_fix": null,
  "title_valid": true,
  "title_fix": null,
  "remove_add": ["Thêm selector mới vào remove_selectors nếu thấy noise mới"],
  "notes": null
}}
"""

    @staticmethod
    def learning_3_special_content(html_snippet: str, url: str) -> str:
        return f"""Phân tích Chapter 3 để phát hiện nội dung đặc biệt: bảng, công thức toán, ký hiệu đặc biệt.

URL Chapter 3: {url}
HTML (tối đa 8000 ký tự):
{html_snippet}

Trả về JSON (CHỈ JSON thuần):
{{
  "has_tables": false,
  "table_evidence": null,
  "has_math": false,
  "math_format": null,
  "math_evidence": [],
  "special_symbols": [],
  "notes": null
}}

math_format: "latex" | "mathjax" | "plain_unicode" | null
"""

    @staticmethod
    def learning_4_formatting(html_snippet: str, url: str) -> str:
        return f"""Phân tích Chapter 4 để phát hiện các element định dạng đặc biệt:
system notification box, hidden/spoiler text, author's note / translator's note.

URL Chapter 4: {url}
HTML (tối đa 8000 ký tự):
{html_snippet}

Trả về JSON (CHỈ JSON thuần):
{{
  "system_box": {{"found": false, "selectors": [], "convert_to": "blockquote", "prefix": "**System:**"}},
  "hidden_text": {{"found": false, "selectors": [], "convert_to": "spoiler_tag"}},
  "author_note": {{"found": false, "selectors": [], "convert_to": "blockquote_note"}},
  "bold_italic": true,
  "hr_dividers": true,
  "image_alt_text": false,
  "notes": null
}}
"""

    @staticmethod
    def find_first_chapter(candidates: str, base_url: str) -> str:
        return f"""Đây là các URL candidate cho Chapter 1 của truyện:
{candidates}

Trang nguồn: {base_url}

Trả về JSON (CHỈ JSON thuần):
{{"first_chapter_url": "URL của Chapter 1 — chương đầu tiên, số nhỏ nhất. null nếu không xác định được."}}
"""

    @staticmethod
    def classify_and_find(hint_block: str, html_snippet: str, base_url: str) -> str:
        return f"""Phân loại trang và tìm URL chương tiếp theo (emergency fallback).

URL hiện tại: {base_url}
Link điều hướng:
{hint_block}

HTML (tối đa 5000 ký tự):
{html_snippet}

Trả về JSON (CHỈ JSON thuần):
{{
  "page_type": "chapter",
  "next_url": "URL chương tiếp theo hoặc null",
  "first_chapter_url": null
}}
"""

    @staticmethod
    def verify_ads(candidates: list[str], domain: str) -> str:
        numbered = "\n".join(
            f"  {i + 1:>2}. {line!r}"
            for i, line in enumerate(candidates)
        )
        return f"""Bạn là chuyên gia lọc nội dung web novel. Nhiệm vụ: xác nhận dòng nào là ADS/WATERMARK thực sự.

Domain scrape: {domain}

Các dòng đã bị lọc ra khỏi nội dung truyện (xuất hiện nhiều lần):
{numbered}

TIÊU CHÍ ADS/WATERMARK (xác nhận là TRUE):
  ✓ Stolen content notice, piracy notice
  ✓ "Read at [site]", "Visit [site]", "Find this novel at..."
  ✓ Quảng cáo Patreon / Ko-fi / donation
  ✓ Attribution dịch thuật boilerplate lặp lại
  ✓ Navigation label lặp lại (Prev/Next/TOC)
  ✓ Copyright watermark chèn vào content

KHÔNG PHẢI ADS (FALSE POSITIVE):
  ✗ Dialogue nhân vật tình cờ đề cập tên website
  ✗ Nội dung truyện đề cập dịch thuật trong context
  ✗ Từ generic: "search", "log in", "read", "find"

Trả về JSON (CHỈ JSON thuần):
{{
  "confirmed_ads": ["Chép NGUYÊN VĂN các dòng xác nhận là ads. [] nếu không có."],
  "false_positives": ["Chép NGUYÊN VĂN các dòng là false positive. [] nếu không có."],
  "notes": null
}}
"""


# ── Helper ────────────────────────────────────────────────────────────────────

def _format_profile_summary(profile: dict) -> str:
    lines = [
        f"  content_selector:  {profile.get('content_selector')!r}",
        f"  next_selector:     {profile.get('next_selector')!r}",
        f"  title_selector:    {profile.get('title_selector')!r}",
        f"  remove_selectors:  {profile.get('remove_selectors', [])}",
        f"  nav_type:          {profile.get('nav_type')!r}",
        f"  has_tables:        {profile.get('formatting_rules', {}).get('tables', False)}",
        f"  has_math:          {profile.get('formatting_rules', {}).get('math_support', False)}",
        f"  system_box:        {bool(profile.get('formatting_rules', {}).get('system_box', {}).get('found'))}",
        f"  author_note:       {bool(profile.get('formatting_rules', {}).get('author_note', {}).get('found'))}",
    ]
    return "\n".join(lines)