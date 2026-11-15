"""Các hàm tạo prompt ngắn gọn, có cấu trúc phục vụ gọi LLM trong Cào Text v2."""
from __future__ import annotations

from typing import Any


def prompt_analyze_site(
    skeleton: str | list[str],
    url: str | list[str],
    *,
    candidates: dict[str, Any] | None = None,
    repeated_lines: list[str] | None = None,
    raw_titles: list[str] | None = None,
) -> str:
    """Tạo prompt yêu cầu AI phân tích DOM skeleton (1–2 chương) + ứng viên + naming cho site mới (Phase 4)."""
    urls_str = ", ".join(url) if isinstance(url, list) else url
    if isinstance(skeleton, list):
        skeleton_block = "\n\n".join(
            f"--- CHƯƠNG MẪU #{i + 1} ---\n{sk}" for i, sk in enumerate(skeleton)
        )
    else:
        skeleton_block = skeleton

    extra_blocks: list[str] = []
    if candidates:
        extra_blocks.append(f"=== ỨNG VIÊN HEURISTIC ===\n{candidates}")
    if repeated_lines:
        lines_str = "\n".join(f"  - {ln!r}" for ln in repeated_lines[:30])
        extra_blocks.append(f"=== CÁC DÒNG LẶP LẠI GIỮA CÁC CHƯƠNG ===\n{lines_str}")
    if raw_titles:
        titles_str = "\n".join(f"  - {t!r}" for t in raw_titles[:10])
        extra_blocks.append(f"=== TIÊU ĐỀ THÔ (<title> / <h1>) ===\n{titles_str}")

    extra_section = ("\n\n" + "\n\n".join(extra_blocks)) if extra_blocks else ""

    return f"""Bạn là chuyên gia bóc tách dữ liệu web novel (CSS selector extraction & naming).
Nhiệm vụ: Phân tích cấu trúc DOM skeleton từ URL: {urls_str}

Hãy xác định chính xác các thành phần sau:
1. `content_selector`: CSS selector cho vùng chứa nội dung truyện chính (ưu tiên thẻ bao bọc sát nhất chứa toàn bộ các đoạn văn bản, KHÔNG bao bọc khu vực bình luận, đánh giá, bảng điều khiển hoặc nút chia sẻ).
2. `title_selector`: CSS selector cho tiêu đề chương (h1, h2, hoặc class tiêu đề).
3. `next_selector` và `nav_type`: CSS selector trỏ tới nút/liên kết chương kế tiếp và loại điều hướng ("selector", "rel_next", "anchor_text", "slug_increment", "fanfic", "dropdown").
4. `remove_selectors` và `watermark_selectors`: Danh sách CSS selector phần tử rác (quảng cáo, nút vote, bình luận, social) và watermark ẩn chèn giữa chương.
5. `ads_keywords`: Các dòng rác/quảng cáo/watermark văn bản thuần lặp lại cần xóa.
6. Chính sách ảnh (`download_images`, `image_selector`) và quy tắc định dạng (`formatting_rules`: bảng LitRPG, hộp hệ thống, lời tác giả).
7. Đặt tên chuẩn hóa (`story_name_clean`, `chapter_keyword`, `has_chapter_subtitle`, `story_prefix_strip`).
8. `requires_playwright`: Đặt True nếu nội dung chương bị rỗng/mã hóa cần trình duyệt render.
{extra_section}

=== DOM SKELETON ===
{skeleton_block}
"""


def prompt_repair_site(
    skeleton: str,
    url: str,
    current_profile: dict[str, Any],
    failure_reason: str,
) -> str:
    """Tạo prompt yêu cầu AI sửa đổi bộ chọn khi kiểm chứng thực tế thất bại."""
    cur_content = current_profile.get("content_selector")
    cur_title = current_profile.get("title_selector")
    cur_next = current_profile.get("next_selector")
    cur_removes = current_profile.get("remove_selectors", [])

    return f"""Bộ chọn hiện tại kiểm chứng thất bại trên trang: {url}
Nguyên nhân lỗi:
{failure_reason}

Bộ chọn hiện tại đang dùng:
- content_selector: {cur_content!r}
- title_selector: {cur_title!r}
- next_selector: {cur_next!r}
- remove_selectors: {cur_removes!r}

Dựa vào DOM skeleton cập nhật dưới đây, hãy tìm bộ chọn mới chính xác hơn để sửa triệt để lỗi trên.

=== DOM SKELETON ===
{skeleton}
"""


def prompt_classify_page(
    skeleton: str,
    url: str,
    link_candidates: list[str] | None = None,
) -> str:
    """Tạo prompt yêu cầu AI phân loại trang và tìm link chương 1 hoặc chương kế tiếp."""
    candidates_block = ""
    if link_candidates:
        candidates_str = "\n".join(f"  - {lnk}" for lnk in link_candidates[:30])
        candidates_block = f"\nDanh sách liên kết ứng viên tìm thấy trên trang:\n{candidates_str}\n"

    return f"""Phân loại trang web và trích xuất liên kết điều hướng từ URL: {url}
{candidates_block}
Nhiệm vụ:
1. `page_type`: Xác định xem đây là trang:
   - "index": Trang mục lục, danh sách chương, hoặc trang thông tin giới thiệu truyện.
   - "chapter": Trang nội dung của một chương truyện cụ thể.
   - "unknown": Không xác định được.
2. Nếu là trang "index": Tìm URL trỏ tới chương 1 (`first_chapter_url`).
3. Nếu là trang "chapter": Tìm URL trỏ tới chương kế tiếp (`next_chapter_url`).
4. Trích xuất `story_title` (tên truyện) và `chapter_title` (tên chương nếu có).

=== DOM SKELETON ===
{skeleton}
"""


def prompt_extract_content(skeleton_or_html: str, url: str) -> str:
    """Tạo prompt emergency fallback trích xuất nội dung chương thuần văn bản."""
    return f"""Bạn là công cụ trích xuất văn bản truyện.
Nhiệm vụ: Trích xuất TOÀN BỘ nội dung văn bản của chương truyện từ trang: {url}

Yêu cầu nghiêm ngặt:
- Chỉ lấy nội dung truyện thật của tác giả.
- Loại bỏ hoàn toàn mọi quảng cáo, lời kêu gọi like/share/vote/donate, thanh điều hướng, bản quyền website.
- Định dạng nội dung: Mỗi đoạn văn cách nhau bằng 2 dòng ngắt dòng (blank line).
- Trích xuất `title` của chương và `next_url` nếu phát hiện thấy link chương tiếp theo.

=== NỘI DUNG TRANG ===
{skeleton_or_html}
"""


def prompt_verify_ads_lines(candidate_lines: list[str], domain: str) -> str:
    """Tạo prompt yêu cầu AI phân loại các dòng văn bản lặp lại thành ads hoặc văn bản an toàn."""
    formatted_lines = "\n".join(f"[{i + 1}] {line!r}" for i, line in enumerate(candidate_lines))

    return f"""Dưới đây là các câu văn bản lặp lại nhiều lần được phát hiện trên website novel: {domain}
Nhiệm vụ: Phân loại từng câu vào một trong hai nhóm:

1. `ad_lines`: Các câu THỰC SỰ là quảng cáo, watermark của web, link trang khác, lời kêu gọi vote/donate, hoặc thông báo của nhóm dịch lặp lại.
2. `safe_lines`: Các câu là NỘI DUNG TRUYỆN THẬT (lời thoại nhân vật, câu miêu tả cốt truyện, độc thoại, danh xưng). TUYỆT ĐỐI KHÔNG ĐƯỢC XÓA NHẦM NỘI DUNG TRUYỆN.

=== DANH SÁCH CÂU CẦN XÉT ===
{formatted_lines}
"""


def prompt_txt_pattern(sample_lines: str) -> str:
    """Tạo prompt tìm regex ranh giới chương cho file TXT không theo quy chuẩn thông thường."""
    return f"""Dưới đây là đoạn trích mẫu từ một file tiểu thuyết định dạng văn bản thô (TXT).
File này không dùng các từ khóa ranh giới thông thường như 'Chương N' hay 'Chapter N'.

Nhiệm vụ:
Phân tích mẫu và tạo một Python regular expression (`chapter_regex`) để khớp chính xác dòng tiêu đề của mỗi chương mới (ví dụ khớp 'Hồi 1', 'Tiết 12', 'Quyển 3 Chương 4', 'Phần thứ nhất...').

Yêu cầu regex:
- Khớp từ đầu dòng (`^`).
- Khớp linh hoạt số chương (số Ả Rập 1, 2 hoặc số chữ La Mã/Hán tự).
- Không khớp các câu thoại hoặc miêu tả trong thân bài.

=== ĐOẠN TRÍCH MẪU TXT ===
{sample_lines}
"""


def prompt_epub_rules(
    docs_meta_summary: str,
    toc_titles: list[str] | None = None,
) -> str:
    """Tạo prompt phân tích mẫu tài liệu EPUB + TOC để sinh QUY TẮC chia chương (Phase 6.2 & §7.3)."""
    toc_block = ""
    if toc_titles:
        toc_str = "\n".join(f"  - {t}" for t in toc_titles[:150])
        toc_block = f"\n=== TIÊU ĐỀ TRONG MỤC LỤC (TOC) ===\n{toc_str}\n"

    return f"""Phân tích cấu trúc mẫu tài liệu trong sách EPUB để trích xuất QUY TẮC phân chia chương (KHÔNG liệt kê từng chương).
Dưới đây là thông tin mẫu các tài liệu ở đầu, giữa và cuối sách (id, href, tiêu đề, số từ):
{toc_block}
=== MẪU TÀI LIỆU EPUB (ĐẦU / GIỮA / CUỐI) ===
{docs_meta_summary}

Nhiệm vụ: Trả về bộ quy tắc tổng quát để code tự động áp dụng lên toàn bộ sách:
1. `chapter_title_regex`: Regex khớp tiêu đề các chương chính (ví dụ `^(?:Chapter|Chương)\\s+\\d+`).
2. `divider_title_regex`: Regex khớp trang ngăn cách Phần/Quyển (`Part`, `Book`, `Volume`, `Quyển`) để gộp vào chương liền sau.
3. `front_matter_keywords` & `front_matter_hrefs`: Từ khóa tiêu đề/filename và danh sách href thuộc phần đầu sách cần bỏ qua (cover, bản quyền, lời tựa, mục lục).
4. `back_matter_keywords` & `back_matter_hrefs`: Từ khóa tiêu đề/filename và danh sách href thuộc phần cuối sách cần bỏ qua (lời bạt, phụ lục, quảng cáo).
5. `merge_unnamed_into_previous`: Đặt True nếu một chương dài bị tách thành nhiều file liên tiếp mà các file sau không có tiêu đề riêng.
"""
