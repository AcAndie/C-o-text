"""Kiểm chứng SiteProfile (V1–V6) trên các chương mẫu bằng code thuần.

Bộ 6 quy tắc kiểm chứng (Phase 4):
- V1: content_selector khớp trong mọi mẫu (100% mẫu).
- V2: Độ dài ≥300 ký tự và ≥60% khối text dày nhất (không quá hẹp);
      Link density ≤30% và không chứa thành phần UI/bình luận/quảng cáo (không quá rộng —
      đánh fail profile cũ của Webnovel dùng `div.cha-page`).
- V3: title_selector tìm thấy ở ≥80% mẫu và khác nhau giữa các chương (loại trừ logo/tên site).
- V4: next dẫn đúng URL chương mẫu kế tiếp (≥75% các chuyển tiếp mẫu liên tiếp).
- V5: remove_selectors không làm mất >20% nội dung (bảo vệ chống xóa nhầm toàn bộ văn bản).
- V6: Mỗi dòng ads_keywords xuất hiện nguyên văn ở ≥2 mẫu (loại bỏ từ khóa bịa đặt).
"""
from __future__ import annotations

import copy
import logging
import math
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urldefrag

from bs4 import BeautifulSoup

from cao_text.extract.nav import find_next_url
from cao_text.extract.title import extract_title

logger = logging.getLogger(__name__)

# Các bộ chọn biểu thị thành phần UI/khung trang/bình luận (không thuộc văn xuôi truyện)
_MAJOR_UI_NOISE_SELECTORS: tuple[str, ...] = (
    # Webnovel UI blocks
    ".cha-hd",
    ".cha-header",
    ".cha-foot",
    ".cha-page-ft",
    ".cha-info",
    ".cha-bts",
    ".cha-loader",
    ".cha-modal",
    ".j_bottom_comment_area",
    ".j_bottom_comments",
    ".j_bottom",
    ".j_chapter_end",
    ".j_power_rank_wrap",
    ".j_trigger_power_modal",
    ".review-list",
    ".j_quote",
    # RoyalRoad UI blocks
    "#comments",
    ".comments-list",
    ".comment-container",
    ".chapter-comments",
    "#chapter-comments",
    ".reading-settings",
    "#settings-popover",
    ".author-note-portlet",
    # Generic page wrappers
    "header",
    "footer",
    "nav",
    ".sidebar",
)


@dataclass
class RuleResult:
    """Kết quả kiểm chứng của một quy tắc (V1..V6)."""

    rule_id: str
    name: str
    passed: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class VerificationResult:
    """Tổng hợp kết quả kiểm chứng profile trên tập chương mẫu."""

    passed: bool
    rules: dict[str, RuleResult] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def v1(self) -> RuleResult:
        return self.rules["V1"]

    @property
    def v2(self) -> RuleResult:
        return self.rules["V2"]

    @property
    def v3(self) -> RuleResult:
        return self.rules["V3"]

    @property
    def v4(self) -> RuleResult:
        return self.rules["V4"]

    @property
    def v5(self) -> RuleResult:
        return self.rules["V5"]

    @property
    def v6(self) -> RuleResult:
        return self.rules["V6"]

    def summary(self) -> str:
        """Tạo chuỗi tổng kết lỗi/cảnh báo phục vụ prompt repair_site hoặc log issues.md."""
        lines: list[str] = []
        for rid in ("V1", "V2", "V3", "V4", "V5", "V6"):
            res = self.rules.get(rid)
            if res:
                icon = "✓" if res.passed else "✗"
                lines.append(f"[{icon}] {res.rule_id} ({res.name}): {res.message}")
        if self.errors:
            lines.append("\nCác lỗi nghiêm trọng cần sửa:")
            for err in self.errors:
                lines.append(f"  - {err}")
        return "\n".join(lines)


def _get_val(obj: Any, key: str, default: Any = None) -> Any:
    """Đọc thuộc tính linh hoạt từ SiteProfile, SiteAnalysisOutput hoặc dict."""
    if hasattr(obj, key):
        return getattr(obj, key)
    if isinstance(obj, dict):
        return obj.get(key, default)
    return default


def _normalize_url(url: str | None) -> str:
    """Chuẩn hóa URL: bỏ fragment và dấu gạch chéo cuối để so sánh tương đối."""
    if not url:
        return ""
    defrag, _ = urldefrag(url)
    return defrag.rstrip("/")


def _ensure_soups(
    samples: list[tuple[str, str]],
    soups: list[BeautifulSoup] | None = None,
) -> list[BeautifulSoup]:
    """Tái sử dụng danh sách BeautifulSoup hoặc parse một lần duy nhất."""
    if soups is not None:
        return soups
    return [BeautifulSoup(html, "lxml") for _, html in samples]


# ── V1: Content Selector Match ────────────────────────────────────────────────


def verify_v1(
    content_selector: str | None,
    samples: list[tuple[str, str]],
    soups: list[BeautifulSoup],
) -> RuleResult:
    """V1: content_selector phải khớp và tìm thấy phần tử trong mọi mẫu (100% mẫu)."""
    if not content_selector or not content_selector.strip():
        return RuleResult(
            rule_id="V1",
            name="content_selector_exists",
            passed=False,
            message="content_selector bị rỗng",
            details={"matched_samples": 0, "total_samples": len(samples)},
        )

    matched = 0
    total = len(samples)
    for idx, (url, _) in enumerate(samples):
        soup = soups[idx]
        try:
            els = soup.select(content_selector)
        except Exception as e:
            return RuleResult(
                rule_id="V1",
                name="content_selector_exists",
                passed=False,
                message=f"CSS selector {content_selector!r} không hợp lệ: {e}",
                details={"error": str(e)},
            )
        if els:
            matched += 1
        else:
            return RuleResult(
                rule_id="V1",
                name="content_selector_exists",
                passed=False,
                message=f"content_selector {content_selector!r} không tìm thấy trên mẫu {idx + 1} ({url})",
                details={"failed_sample_index": idx, "failed_url": url},
            )

    return RuleResult(
        rule_id="V1",
        name="content_selector_exists",
        passed=True,
        message=f"content_selector {content_selector!r} khớp trên toàn bộ {matched}/{total} mẫu",
        details={"matched_samples": matched, "total_samples": total},
    )


# ── V2: Content Quality & Boundaries (Neither Narrow Nor Broad) ───────────────


def verify_v2(
    content_selector: str | None,
    samples: list[tuple[str, str]],
    soups: list[BeautifulSoup],
) -> RuleResult:
    """V2: Độ dài ≥300 ký tự và ≥60% khối text dày nhất (không quá hẹp).

    Link density ≤30% và không chứa thành phần UI/bình luận/quảng cáo
    (không quá rộng — đánh fail profile cũ của Webnovel `div.cha-page`).
    """
    if not content_selector:
        return RuleResult(
            rule_id="V2",
            name="content_boundaries",
            passed=False,
            message="Không thể kiểm tra V2 do content_selector rỗng",
        )

    for idx, (url, _) in enumerate(samples):
        soup = soups[idx]
        try:
            els = soup.select(content_selector)
        except Exception:
            els = []

        if not els:
            return RuleResult(
                rule_id="V2",
                name="content_boundaries",
                passed=False,
                message=f"Không tìm thấy phần tử nội dung trên mẫu {idx + 1}",
                details={"sample_index": idx},
            )

        text = "".join(e.get_text(strip=True) for e in els)
        text_len = len(text)

        # 1. Kiểm tra giới hạn dưới: Độ dài tối thiểu 300 ký tự
        if text_len < 300:
            return RuleResult(
                rule_id="V2",
                name="content_boundaries",
                passed=False,
                message=f"Nội dung quá ngắn ({text_len} < 300 ký tự) trên mẫu {idx + 1} ({url})",
                details={"sample_index": idx, "text_len": text_len},
            )

        # 2. Kiểm tra không quá hẹp: Phải chiếm ≥ 60% khối văn bản lớn nhất trên trang
        body = soup.body or soup
        body_text_len = len(body.get_text(strip=True))
        if body_text_len > 0:
            ratio = text_len / body_text_len
            if ratio < 0.60:
                return RuleResult(
                    rule_id="V2",
                    name="content_boundaries",
                    passed=False,
                    message=f"Nội dung quá hẹp (chiếm {ratio:.1%} < 60% văn bản trang) trên mẫu {idx + 1}",
                    details={"sample_index": idx, "ratio": ratio, "text_len": text_len, "body_len": body_text_len},
                )

        # 3. Kiểm tra Link density: Phải ≤ 30% (tránh nhặt nhầm mục lục/menu)
        link_len = sum(len(a.get_text(strip=True)) for e in els for a in e.find_all("a"))
        link_density = link_len / max(1, text_len)
        if link_density > 0.30:
            return RuleResult(
                rule_id="V2",
                name="content_boundaries",
                passed=False,
                message=f"Mật độ liên kết quá cao ({link_density:.1%} > 30%) trên mẫu {idx + 1}",
                details={"sample_index": idx, "link_density": link_density},
            )

        # 4. Kiểm tra không quá rộng: KHÔNG ĐƯỢC CHỨA UI/BÌNH LUẬN/RÁC
        # Đây là trọng tâm đánh fail `div.cha-page` của Webnovel
        found_ui_elements: list[str] = []
        for e in els:
            for noise_sel in _MAJOR_UI_NOISE_SELECTORS:
                try:
                    if e.select(noise_sel):
                        found_ui_elements.append(noise_sel)
                except Exception:
                    continue

        if found_ui_elements:
            unique_noises = sorted(set(found_ui_elements))
            return RuleResult(
                rule_id="V2",
                name="content_boundaries",
                passed=False,
                message=(
                    f"content_selector {content_selector!r} quá rộng: chứa các phần tử UI/bình luận/quảng cáo "
                    f"({', '.join(unique_noises[:4])}) trên mẫu {idx + 1}"
                ),
                details={
                    "sample_index": idx,
                    "found_noise_selectors": unique_noises,
                    "reason": "outer_wrapper_with_ui",
                },
            )

    return RuleResult(
        rule_id="V2",
        name="content_boundaries",
        passed=True,
        message="Vùng chứa nội dung đạt chuẩn (độ dài, mật độ link và không chứa UI ngoài lề)",
    )


# ── V3: Title Selection & Variance ────────────────────────────────────────────


def verify_v3(
    title_selector: str | None,
    samples: list[tuple[str, str]],
    soups: list[BeautifulSoup],
) -> RuleResult:
    """V3: title tìm thấy ở ≥80% mẫu và khác nhau giữa các chương (loại bỏ logo/tên site)."""
    total = len(samples)
    min_hits = max(1, math.ceil(0.80 * total))
    extracted_titles: list[str] = []

    if title_selector and title_selector.strip():
        # Kiểm tra selector tường minh
        for soup in soups:
            try:
                el = soup.select_one(title_selector)
            except Exception:
                el = None
            if el:
                t = el.get_text(strip=True)
                if 3 <= len(t) <= 250:
                    extracted_titles.append(t)

        hits = len(extracted_titles)
        if hits < min_hits:
            return RuleResult(
                rule_id="V3",
                name="title_quality",
                passed=False,
                message=f"title_selector {title_selector!r} chỉ tìm thấy ở {hits}/{total} mẫu (< 80%)",
                details={"hits": hits, "total": total, "min_required": min_hits},
            )
    else:
        # Nếu không có title_selector, kiểm tra chuỗi fallback (h1, og:title, url_slug)
        for idx, (url, _) in enumerate(samples):
            soup = soups[idx]
            t, method = extract_title(soup, url, profile=None)
            if t and 3 <= len(t) <= 250 and method != "url_slug":
                extracted_titles.append(t)

        hits = len(extracted_titles)
        if hits < min_hits:
            return RuleResult(
                rule_id="V3",
                name="title_quality",
                passed=False,
                message=f"Chuỗi fallback tiêu đề chỉ tìm thấy ở {hits}/{total} mẫu (< 80%)",
                details={"hits": hits, "total": total},
            )

    # Kiểm tra tính biến thiên tiêu đề: nếu có ≥2 mẫu, tiêu đề phải khác nhau giữa các chương
    if total >= 2:
        distinct = len(set(extracted_titles))
        if distinct <= 1:
            static_title = extracted_titles[0] if extracted_titles else ""
            return RuleResult(
                rule_id="V3",
                name="title_quality",
                passed=False,
                message=(
                    f"Tiêu đề không thay đổi giữa các chương (toàn bộ đều là {static_title!r}), "
                    "nghi là tên trang web hoặc logo thay vì tiêu đề chương"
                ),
                details={"distinct_count": distinct, "sample_titles": extracted_titles},
            )

    return RuleResult(
        rule_id="V3",
        name="title_quality",
        passed=True,
        message=f"Tiêu đề hợp lệ (tìm thấy ở {len(extracted_titles)}/{total} mẫu, phân biệt rõ giữa các chương)",
        details={"titles": extracted_titles[:3]},
    )


# ── V4: Next Navigation Verification ──────────────────────────────────────────


def verify_v4(
    profile: Any,
    samples: list[tuple[str, str]],
    soups: list[BeautifulSoup],
) -> RuleResult:
    """V4: next dẫn đúng URL chương mẫu kế tiếp (≥75% các chuyển tiếp mẫu)."""
    total_samples = len(samples)
    if total_samples < 2:
        return RuleResult(
            rule_id="V4",
            name="next_navigation",
            passed=True,
            message="Chỉ có 1 mẫu, bỏ qua kiểm tra chuyển tiếp V4",
        )

    transitions = total_samples - 1
    min_required = max(1, math.ceil(0.75 * transitions))
    correct_count = 0
    failures: list[dict[str, str]] = []
    nav_methods: list[str] = []

    for i in range(transitions):
        curr_url, _ = samples[i]
        next_target_url, _ = samples[i + 1]
        soup = soups[i]

        discovered_url, nav_method = find_next_url(soup, curr_url, profile)
        nav_methods.append(nav_method)

        if discovered_url and _normalize_url(discovered_url) == _normalize_url(next_target_url):
            correct_count += 1
        else:
            failures.append({
                "from_url": curr_url,
                "expected": next_target_url,
                "discovered": discovered_url or "None",
                "method": nav_method,
            })

    if correct_count < min_required:
        first_fail = failures[0] if failures else {}
        return RuleResult(
            rule_id="V4",
            name="next_navigation",
            passed=False,
            message=(
                f"Nút next chỉ dẫn đúng {correct_count}/{transitions} chuyển tiếp chương (< 75%). "
                f"Ví dụ: kỳ vọng {first_fail.get('expected')}, phát hiện {first_fail.get('discovered')}"
            ),
            details={"correct_count": correct_count, "transitions": transitions, "failures": failures},
        )

    primary_method = nav_methods[0] if nav_methods else "unknown"
    return RuleResult(
        rule_id="V4",
        name="next_navigation",
        passed=True,
        message=f"Điều hướng chương kế tiếp dẫn đúng {correct_count}/{transitions} chuyển tiếp liên tiếp (phương thức: {primary_method})",
        details={"correct_count": correct_count, "transitions": transitions, "methods": nav_methods},
    )


# ── V5: Remove Selectors Safety Cap ───────────────────────────────────────────


def verify_v5(
    content_selector: str | None,
    remove_selectors: list[str] | None,
    samples: list[tuple[str, str]],
    soups: list[BeautifulSoup],
    max_strip_ratio: float = 0.20,
) -> RuleResult:
    """V5: remove_selectors không làm mất >20% nội dung (bảo vệ tránh xóa nhầm toàn bộ văn bản)."""
    if not remove_selectors or not content_selector:
        return RuleResult(
            rule_id="V5",
            name="remove_selectors_safety",
            passed=True,
            message="Không có remove_selectors hoặc content_selector, kiểm chứng an toàn",
        )

    cleaned_removes = [s.strip() for s in remove_selectors if isinstance(s, str) and s.strip()]
    if not cleaned_removes:
        return RuleResult(
            rule_id="V5",
            name="remove_selectors_safety",
            passed=True,
            message="Danh sách remove_selectors rỗng",
        )

    max_loss_observed = 0.0

    for idx, (url, _) in enumerate(samples[:3]):
        soup = soups[idx]
        try:
            orig_el = soup.select_one(content_selector)
        except Exception:
            continue
        if not orig_el:
            continue

        orig_len = len(orig_el.get_text(strip=True))
        if orig_len == 0:
            continue

        # Nhân bản riêng khối nội dung để thử nghiệm bóc tách xóa
        clone = copy.copy(orig_el)
        for sel in cleaned_removes:
            try:
                for victim in clone.select(sel):
                    victim.decompose()
            except Exception:
                continue

        stripped_len = len(clone.get_text(strip=True))
        loss_ratio = (orig_len - stripped_len) / orig_len
        if loss_ratio > max_loss_observed:
            max_loss_observed = loss_ratio

        if loss_ratio > max_strip_ratio:
            return RuleResult(
                rule_id="V5",
                name="remove_selectors_safety",
                passed=False,
                message=(
                    f"remove_selectors làm mất {loss_ratio:.1%} (> {int(max_strip_ratio * 100)}%) "
                    f"nội dung trên mẫu {idx + 1} ({url}) — nguy cơ xóa nhầm nội dung truyện"
                ),
                details={"sample_index": idx, "loss_ratio": loss_ratio, "max_allowed": max_strip_ratio},
            )

    return RuleResult(
        rule_id="V5",
        name="remove_selectors_safety",
        passed=True,
        message=f"remove_selectors an toàn (mất tối đa {max_loss_observed:.1%} <= {int(max_strip_ratio * 100)}% nội dung)",
        details={"max_loss_observed": max_loss_observed},
    )


# ── V6: Ads/Watermark Keywords Verbatim Check ─────────────────────────────────


def verify_v6(
    ads_keywords: list[str] | None,
    samples: list[tuple[str, str]],
    soups: list[BeautifulSoup],
    content_selector: str | None = None,
) -> RuleResult:
    """V6: Mỗi dòng rác/quảng cáo trong ads_keywords phải xuất hiện nguyên văn ở ≥2 mẫu.

    Giúp ngăn chặn AI ảo giác bịa ra các câu thoại của nhân vật làm từ khóa lọc quảng cáo.
    """
    if not ads_keywords:
        return RuleResult(
            rule_id="V6",
            name="ads_keywords_verbatim",
            passed=True,
            message="Không có ads_keywords cần kiểm chứng",
        )

    # Thu thập văn bản của tất cả mẫu
    sample_texts: list[str] = []
    for soup in soups:
        target_el = None
        if content_selector:
            try:
                target_el = soup.select_one(content_selector)
            except Exception:
                target_el = None
        if target_el is None:
            target_el = soup.body or soup

        sample_texts.append(target_el.get_text())

    total_samples = len(samples)
    min_appearances = 2 if total_samples >= 3 else 1

    invalid_keywords: list[str] = []
    valid_keywords: list[str] = []

    for kw in ads_keywords:
        kw_clean = kw.strip()
        if not kw_clean:
            continue
        appearances = sum(1 for text in sample_texts if kw_clean.lower() in text.lower())
        if appearances >= min_appearances:
            valid_keywords.append(kw_clean)
        else:
            invalid_keywords.append(kw_clean)

    if invalid_keywords:
        return RuleResult(
            rule_id="V6",
            name="ads_keywords_verbatim",
            passed=False,
            message=(
                f"Có {len(invalid_keywords)}/{len(ads_keywords)} từ khóa rác không xuất hiện ở "
                f"≥{min_appearances} mẫu: {invalid_keywords[:3]}"
            ),
            details={
                "invalid_keywords": invalid_keywords,
                "valid_keywords": valid_keywords,
                "min_appearances": min_appearances,
            },
        )

    return RuleResult(
        rule_id="V6",
        name="ads_keywords_verbatim",
        passed=True,
        message=f"Toàn bộ {len(valid_keywords)} ads_keywords đều xuất hiện ở ≥{min_appearances} mẫu",
        details={"valid_keywords": valid_keywords},
    )


# ── Full Verification Entry Point ─────────────────────────────────────────────


def verify_site_profile(
    profile: Any,
    samples: list[tuple[str, str]],
    soups: list[BeautifulSoup] | None = None,
) -> VerificationResult:
    """Kiểm chứng toàn diện 6 quy tắc V1–V6 cho SiteProfile trên tập mẫu HTML.

    Trả về VerificationResult với `passed=True` khi tất cả các quy tắc bắt buộc đều vượt qua.
    """
    if not samples:
        return VerificationResult(
            passed=False,
            errors=["Tập mẫu HTML kiểm chứng rỗng (< 1 mẫu)"],
        )

    parsed_soups = _ensure_soups(samples, soups)

    content_selector = _get_val(profile, "content_selector")
    title_selector = _get_val(profile, "title_selector")
    remove_selectors = _get_val(profile, "remove_selectors") or []
    ads_keywords = _get_val(profile, "ads_keywords") or []

    res_v1 = verify_v1(content_selector, samples, parsed_soups)
    res_v2 = verify_v2(content_selector, samples, parsed_soups)
    res_v3 = verify_v3(title_selector, samples, parsed_soups)
    res_v4 = verify_v4(profile, samples, parsed_soups)
    res_v5 = verify_v5(content_selector, remove_selectors, samples, parsed_soups)
    res_v6 = verify_v6(ads_keywords, samples, parsed_soups, content_selector)

    rules = {
        "V1": res_v1,
        "V2": res_v2,
        "V3": res_v3,
        "V4": res_v4,
        "V5": res_v5,
        "V6": res_v6,
    }

    errors: list[str] = []
    warnings: list[str] = []

    # V1, V2, V4, V5 là điều kiện bắt buộc (hard failures)
    for rid in ("V1", "V2", "V4", "V5"):
        r = rules[rid]
        if not r.passed:
            errors.append(f"[{rid}] {r.message}")

    # V3 (tiêu đề) và V6 (ads keywords)
    if not res_v3.passed:
        # Nếu tiêu đề bị trùng lặp (site logo) -> lỗi nghiêm trọng
        if "không thay đổi" in res_v3.message.lower():
            errors.append(f"[V3] {res_v3.message}")
        else:
            warnings.append(f"[V3] {res_v3.message}")

    if not res_v6.passed:
        warnings.append(f"[V6] {res_v6.message}")

    overall_passed = len(errors) == 0

    return VerificationResult(
        passed=overall_passed,
        rules=rules,
        errors=errors,
        warnings=warnings,
    )
