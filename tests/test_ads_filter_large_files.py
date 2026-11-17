"""tests/test_ads_filter_large_files.py — Kiểm thử AdsFilter cho file lớn và bảo vệ thoại (§7.3 & Task 6.4)."""
from __future__ import annotations

import math
from pathlib import Path

from cao_text.html.ads import (
    AdsFilter,
    compute_auto_threshold,
    is_likely_dialogue_or_scene_break,
    is_valid_ads_keyword,
)

# ── 1. Kiểm tra công thức ngưỡng scale theo số chương ─────────────────────────

def test_compute_auto_threshold() -> None:
    # Với số chương nhỏ hoặc bằng 0: tối thiểu bằng 10
    assert compute_auto_threshold(0) == 10
    assert compute_auto_threshold(5) == 10
    assert compute_auto_threshold(50) == 10
    assert compute_auto_threshold(100) == 10
    assert compute_auto_threshold(300) == 10  # ceil(0.03 * 300) = 9 <= 10

    # Với số chương lớn > 334 chương: scale theo 0.03 * số chương
    assert compute_auto_threshold(350) == math.ceil(0.03 * 350)  # 11
    assert compute_auto_threshold(500) == 15
    assert compute_auto_threshold(1000) == 30
    assert compute_auto_threshold(1300) == 39
    assert compute_auto_threshold(1600) == 48
    assert compute_auto_threshold(1631) == 49


# ── 2. Kiểm tra nhận diện câu thoại / chuyển cảnh ngắn cần bảo vệ ─────────────

def test_is_likely_dialogue_or_scene_break_vietnamese() -> None:
    # Lời dẫn thoại kết thúc bằng dấu hai chấm (lỗi §7.3 "Hàn Tuyệt nói:")
    assert is_likely_dialogue_or_scene_break("Hàn Tuyệt nói:") is True
    assert is_likely_dialogue_or_scene_break("Lâm Phong thầm nghĩ:") is True
    assert is_likely_dialogue_or_scene_break("Tiêu Viêm thở dài：") is True

    # Câu chuyển cảnh ngắn < 25 ký tự (lỗi §7.3 "Cùng lúc đó.")
    assert is_likely_dialogue_or_scene_break("Cùng lúc đó.") is True
    assert is_likely_dialogue_or_scene_break("Một ngày sau.") is True
    assert is_likely_dialogue_or_scene_break("Ba tháng sau.") is True
    assert is_likely_dialogue_or_scene_break("Đêm khuya thanh vắng.") is True

    # Bắt đầu bằng dấu ngoặc kép hoặc gạch đầu dòng thoại
    assert is_likely_dialogue_or_scene_break('“Ngươi rốt cuộc là ai?”') is True
    assert is_likely_dialogue_or_scene_break('"Ta không biết."') is True
    assert is_likely_dialogue_or_scene_break("«Hãy đi mau!»") is True
    assert is_likely_dialogue_or_scene_break("- Không thể nào như vậy được.") is True
    assert is_likely_dialogue_or_scene_break("— Đi thôi.") is True


def test_is_likely_dialogue_or_scene_break_watermark_not_protected() -> None:
    # Dù ngắn hoặc kết thúc bằng hai chấm nhưng nếu chứa watermark/URL thì KHÔNG được bảo vệ
    assert is_likely_dialogue_or_scene_break("Website: https://novel.vn") is False
    assert is_likely_dialogue_or_scene_break("Read on royalroad:") is False
    assert is_likely_dialogue_or_scene_break("Vote power stone:") is False
    assert is_likely_dialogue_or_scene_break("Donate paypal:") is False
    assert is_likely_dialogue_or_scene_break("discord.gg/novel") is False


# ── 3. Mô phỏng bộ truyện 1500 chương không xóa nhầm thoại (§7.3) ────────────

def test_ads_filter_large_novel_simulation(tmp_path: Path) -> None:
    ads_file = tmp_path / "ads_keywords.json"
    ads = AdsFilter(
        domain="epub:dinh_cap_khi_van",
        ads_db_file=ads_file,
        story_title="Đỉnh Cấp Khí Vận",
    )

    # 1. Dòng thoại "Hàn Tuyệt nói:" xuất hiện ở cạnh của 20 chương
    dialogue_line = "Hàn Tuyệt nói:"
    for _ in range(20):
        ads._suspects[dialogue_line.lower()] += 1

    # 2. Dòng quảng cáo thật có watermark domain xuất hiện ở cạnh của 50 chương
    real_ad_line = "Truy cập website truyenhdt.com để theo dõi chương mới."
    for _ in range(50):
        ads._suspects[real_ad_line.lower()] += 1

    # Ngưỡng tự động với bộ truyện 1500 chương: max(10, ceil(0.03 * 1500)) = 45
    auto_threshold = compute_auto_threshold(total_chapters=1500)
    assert auto_threshold == 45

    auto_candidates, ai_candidates = ads.get_candidates_by_frequency(
        auto_threshold=auto_threshold,
        total_chapters=1500,
    )

    # Dòng thoại (20 lần) < 45 lần -> không bao giờ nằm trong auto_candidates
    assert dialogue_line.lower() not in auto_candidates

    # Giả sử dòng thoại lặp lại tới 60 lần (> 45 lần):
    ads._suspects[dialogue_line.lower()] = 60
    auto_candidates_boosted, ai_candidates_boosted = ads.get_candidates_by_frequency(
        auto_threshold=auto_threshold,
        total_chapters=1500,
    )
    # Vẫn bị chặn khỏi auto_candidates vì is_likely_dialogue_or_scene_break = True!
    assert dialogue_line.lower() not in auto_candidates_boosted
    assert dialogue_line.lower() in ai_candidates_boosted

    # Trong khi đó, dòng quảng cáo thật (50 lần >= 45) PHẢI nằm trong auto_candidates
    assert real_ad_line.lower() in auto_candidates

    # Áp dụng tự động
    added = ads.apply_verified(auto_candidates_boosted, is_auto=True)
    assert added == 1  # Chỉ thêm real_ad_line, KHÔNG thêm dialogue_line!
    assert dialogue_line.lower() not in ads.keywords
    assert real_ad_line.lower() in ads.keywords


def test_is_valid_ads_keyword_protections() -> None:
    # Quá ngắn (< 8 chars)
    assert is_valid_ads_keyword("ngắn") is False
    # Trùng tên truyện
    assert is_valid_ads_keyword("Đỉnh Cấp Khí Vận", story_title="Đỉnh Cấp Khí Vận") is False
    # Thẻ HTML
    assert is_valid_ads_keyword("<div class='ads'>click</div>") is False
    # Điều hướng
    assert is_valid_ads_keyword("Next Chapter") is False
    assert is_valid_ads_keyword("Chương sau") is False
