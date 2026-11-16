"""Tìm ứng viên content/title/next bằng heuristic và code thuần (không gọi AI).

Thu thập và xếp hạng ứng viên cho:
1. content_selector: vùng chứa nội dung có mật độ text cao, cấu trúc văn xuôi,
   ổn định qua các mẫu, ưu tiên container chặt chẽ tránh bọc UI/bình luận/quảng cáo.
2. title_selector: bộ chọn tiêu đề chương thay đổi giữa các chương.
3. next_selector / nav_type: liên kết chuyển tiếp chương kế tiếp (kiểm chứng bằng URL chuyển tiếp thật nếu có).
4. repeated_lines: các dòng lặp lại giữa nhiều chương nghi là rác, quảng cáo hoặc watermark.
"""
from __future__ import annotations

import logging
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urldefrag, urljoin

from bs4 import BeautifulSoup, Tag

from cao_text.html.filter import KNOWN_NOISE_SELECTORS

logger = logging.getLogger(__name__)

# Pattern kiểm tra tên CSS identifier an toàn (tránh class Tailwind hoặc ký tự đặc biệt gây lỗi select)
_SAFE_CSS_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")

# Pattern phát hiện từ khóa số/chương trong tiêu đề
_CHAPTER_KEYWORD_RE = re.compile(
    r"\b(?:chapter|chương|chap|ep|episode|tiết|hồi|bài|quyển|phần)\b|\b\d+\b",
    re.IGNORECASE,
)

# Pattern phát hiện text liên kết "Chương sau / Next"
_NEXT_TEXT_RE = re.compile(
    r"^\s*(?:next(?:\s+chapter)?|chương\s+(?:sau|tiếp)|tiếp(?:\s+theo)?|sau|>|>>|→|forward)\s*$",
    re.IGNORECASE,
)

# Pattern nhận diện slug chương có thể tăng số
_SLUG_INCREMENT_RE = re.compile(
    r"^(.*?)([-_/]?(?:chapter|chap|ch|c|ep|episode|tiet)?[-_]?)(\d+)(.*?)$",
    re.IGNORECASE,
)


@dataclass
class ContentCandidate:
    """Ứng viên CSS selector cho vùng chứa nội dung truyện."""

    selector: str
    hit_count: int
    total_samples: int
    avg_length: float
    min_length: int
    max_length: int
    link_density: float
    has_p_tags: bool
    is_tight_wrapper: bool
    score: float


@dataclass
class TitleCandidate:
    """Ứng viên CSS selector cho tiêu đề chương."""

    selector: str
    hit_count: int
    total_samples: int
    sample_titles: list[str]
    distinct_titles_count: int
    has_chapter_keyword: bool
    score: float


@dataclass
class NextCandidate:
    """Ứng viên điều hướng sang chương kế tiếp."""

    selector: str | None
    nav_type: str  # "selector", "rel_next", "anchor_text", "slug_increment", "dropdown", "fanfic"
    hit_count: int
    total_transitions: int
    resolved_urls: list[str]
    confidence: float
    pattern: str | None = None


@dataclass
class SiteCandidates:
    """Tổng hợp ứng viên trích xuất và thông tin học được từ các chương mẫu."""

    content_candidates: list[ContentCandidate] = field(default_factory=list)
    title_candidates: list[TitleCandidate] = field(default_factory=list)
    next_candidates: list[NextCandidate] = field(default_factory=list)
    repeated_lines: list[str] = field(default_factory=list)
    raw_titles: list[str] = field(default_factory=list)
    best_content_selector: str | None = None
    best_title_selector: str | None = None
    best_next_selector: str | None = None
    best_nav_type: str = "selector"

    def to_prompt_dict(self) -> dict[str, Any]:
        """Tạo dict tóm tắt ngắn gọn để đưa vào AI prompt (Phase 3/4)."""
        return {
            "content_candidates": [
                {
                    "selector": c.selector,
                    "hit_count": f"{c.hit_count}/{c.total_samples}",
                    "avg_length": int(c.avg_length),
                    "link_density": round(c.link_density, 3),
                    "is_tight": c.is_tight_wrapper,
                }
                for c in self.content_candidates[:5]
            ],
            "title_candidates": [
                {
                    "selector": t.selector,
                    "hit_count": f"{t.hit_count}/{t.total_samples}",
                    "sample_titles": t.sample_titles[:3],
                }
                for t in self.title_candidates[:3]
            ],
            "next_candidates": [
                {
                    "selector": n.selector,
                    "nav_type": n.nav_type,
                    "confidence": round(n.confidence, 2),
                    "sample_next_url": n.resolved_urls[0] if n.resolved_urls else None,
                }
                for n in self.next_candidates[:3]
            ],
            "best_guess": {
                "content_selector": self.best_content_selector,
                "title_selector": self.best_title_selector,
                "next_selector": self.best_next_selector,
                "nav_type": self.best_nav_type,
            },
        }


def _is_safe_ident(name: str | None) -> bool:
    """Kiểm tra tên class hoặc id có hợp lệ để tạo CSS selector trực tiếp không."""
    if not name:
        return False
    return bool(_SAFE_CSS_IDENT_RE.match(name))


def _normalize_url(url: str) -> str:
    """Chuẩn hóa URL: bỏ hash fragment và dấu gạch chéo cuối để so khớp."""
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


def _is_ancestor(parent: Tag, child: Tag) -> bool:
    """Kiểm tra xem parent có phải là tổ tiên của child không bằng cách đi ngược con trỏ parent."""
    curr = child.parent
    while curr is not None:
        if curr is parent:
            return True
        curr = curr.parent
    return False


# ── Content Candidate Discovery ───────────────────────────────────────────────


def find_content_candidates(
    samples: list[tuple[str, str]],
    min_chars: int = 300,
    min_matches: int | None = None,
    top_k: int = 10,
    soups: list[BeautifulSoup] | None = None,
) -> list[ContentCandidate]:
    """Tìm và xếp hạng các CSS selector vùng chứa nội dung truyện từ các mẫu HTML."""
    if not samples:
        return []

    total_samples = len(samples)
    effective_min_matches = (
        min_matches
        if min_matches is not None
        else max(1, math.ceil(0.6 * total_samples))
    )

    parsed_soups = _ensure_soups(samples, soups)

    # Bước 1: Thu thập tất cả các selector tiềm năng xuất hiện trong 2 mẫu đầu
    candidate_selectors: set[str] = set()
    target_tags = ("div", "article", "section", "main", "td")

    for soup in parsed_soups[:2]:
        for el in soup.find_all(target_tags):
            text_len = len(el.get_text(strip=True))
            if text_len < min_chars:
                continue

            # Kiểm tra cấu trúc văn xuôi
            p_count = len(el.find_all("p"))
            direct_text_children = sum(
                1
                for child in el.find_all(recursive=False)
                if hasattr(child, "get_text") and len(child.get_text(strip=True)) >= 30
            )
            if max(p_count, direct_text_children) < 2:
                continue

            el_name = el.name
            el_id = el.get("id")
            classes = el.get("class") or []
            if isinstance(classes, str):
                classes = [classes]

            # Tạo selector từ ID an toàn
            if _is_safe_ident(el_id):
                candidate_selectors.add(f"{el_name}#{el_id}")
                candidate_selectors.add(f"#{el_id}")

            # Tạo selector từ Class an toàn
            safe_classes = [c for c in classes if _is_safe_ident(c)]
            for cls in safe_classes:
                candidate_selectors.add(f"{el_name}.{cls}")

            # Compound class nếu có 2 class đặc trưng
            if len(safe_classes) >= 2:
                compound = ".".join(safe_classes[:2])
                candidate_selectors.add(f"{el_name}.{compound}")

            # Thuộc tính ngữ nghĩa chuẩn
            itemprop = el.get("itemprop")
            if itemprop == "articleBody":
                candidate_selectors.add(f"{el_name}[itemprop='articleBody']")

            role = el.get("role")
            if role == "main":
                candidate_selectors.add(f"{el_name}[role='main']")

    if not candidate_selectors:
        return []

    # Bước 2: Kiểm thử từng selector trên tất cả mẫu
    evaluated: list[dict[str, Any]] = []

    for sel in candidate_selectors:
        hit_lengths: list[int] = []
        hit_densities: list[float] = []
        has_p = False

        for soup in parsed_soups:
            try:
                els = soup.select(sel)
            except Exception:
                break
            if not els:
                continue

            text = "".join(e.get_text(strip=True) for e in els)
            text_len = len(text)
            if text_len < min_chars:
                continue

            # Tính link density
            link_len = sum(
                len(a.get_text(strip=True))
                for e in els
                for a in e.find_all("a")
            )
            density = link_len / max(1, text_len)
            hit_densities.append(density)
            hit_lengths.append(text_len)

            if not has_p and any(e.find("p") is not None for e in els):
                has_p = True

        hit_count = len(hit_lengths)
        if hit_count < effective_min_matches:
            continue

        avg_density = sum(hit_densities) / hit_count if hit_count else 0.0
        # Loại bỏ nếu link density quá cao (thực chất là menu / mục lục / widget)
        if avg_density > 0.40:
            continue

        avg_len = sum(hit_lengths) / hit_count if hit_count else 0.0
        evaluated.append({
            "selector": sel,
            "hit_count": hit_count,
            "total_samples": total_samples,
            "avg_length": avg_len,
            "min_length": min(hit_lengths),
            "max_length": max(hit_lengths),
            "link_density": avg_density,
            "has_p_tags": has_p,
            "is_tight_wrapper": True,
        })

    if not evaluated:
        return []

    # Bước 3: Phát hiện outer wrapper vs inner prose wrapper (Webnovel `cha-page` vs `cha-words`)
    first_soup = parsed_soups[0]
    cached_first_els: dict[str, Tag | None] = {}
    for item in evaluated:
        s = item["selector"]
        try:
            cached_first_els[s] = first_soup.select_one(s)
        except Exception:
            cached_first_els[s] = None

    # Tính noise map cho từng candidate trên mẫu 1
    safe_noise_selectors = [s for s in KNOWN_NOISE_SELECTORS if not s.startswith("anno")]
    noise_css = ", ".join(safe_noise_selectors)
    noise_map: dict[str, bool] = {}
    for s, el in cached_first_els.items():
        if el:
            try:
                noise_map[s] = bool(el.select_one(noise_css))
            except Exception:
                noise_map[s] = False
        else:
            noise_map[s] = False

    for a in evaluated:
        sel_a = a["selector"]
        el_a = cached_first_els.get(sel_a)
        if not el_a:
            continue

        for b in evaluated:
            if a is b:
                continue
            sel_b = b["selector"]
            el_b = cached_first_els.get(sel_b)
            if not el_b:
                continue

            # Sử dụng _is_ancestor thay vì el_b in el_a.descendants (chạy trong O(depth) ~ 0.01ms)
            if _is_ancestor(el_a, el_b):
                len_a = len(el_a.get_text(strip=True))
                len_b = len(el_b.get_text(strip=True))
                if len_a > 0 and (len_b / len_a) >= 0.65:
                    if noise_map.get(sel_a) and not noise_map.get(sel_b):
                        a["is_tight_wrapper"] = False
                    elif len_b / len_a >= 0.95 and el_a.name in ("div", "section") and el_b.name in ("div", "article"):
                        a["is_tight_wrapper"] = False

    # Bước 4: Chấm điểm và xếp hạng
    results: list[ContentCandidate] = []
    for item in evaluated:
        hit_ratio = item["hit_count"] / total_samples
        score = hit_ratio * 50.0

        # Ưu tiên link density thấp
        score += (1.0 - item["link_density"]) * 20.0

        # Ưu tiên có thẻ <p>
        if item["has_p_tags"]:
            score += 15.0

        # Ưu tiên độ dài hợp lý với tiểu thuyết (>= 1000 ký tự)
        if item["avg_length"] >= 1000:
            score += 15.0

        # Ưu tiên container chặt chẽ, phạt nặng container bọc UI rác
        if item["is_tight_wrapper"]:
            score += 20.0
        else:
            score -= 35.0

        # Ưu tiên selector có tag rõ ràng (vd div.content hơn .content)
        if "." in item["selector"] and not item["selector"].startswith("."):
            score += 5.0
        elif "#" in item["selector"] and not item["selector"].startswith("#"):
            score += 5.0

        results.append(
            ContentCandidate(
                selector=item["selector"],
                hit_count=item["hit_count"],
                total_samples=item["total_samples"],
                avg_length=item["avg_length"],
                min_length=item["min_length"],
                max_length=item["max_length"],
                link_density=item["link_density"],
                has_p_tags=item["has_p_tags"],
                is_tight_wrapper=item["is_tight_wrapper"],
                score=round(score, 2),
            )
        )

    results.sort(key=lambda x: (x.score, x.hit_count, x.avg_length), reverse=True)
    return results[:top_k]


# ── Title Candidate Discovery ─────────────────────────────────────────────────


def find_title_candidates(
    samples: list[tuple[str, str]],
    min_matches: int | None = None,
    top_k: int = 5,
    soups: list[BeautifulSoup] | None = None,
) -> list[TitleCandidate]:
    """Tìm và xếp hạng các CSS selector tiêu đề chương từ các mẫu HTML."""
    if not samples:
        return []

    total_samples = len(samples)
    effective_min_matches = (
        min_matches
        if min_matches is not None
        else max(1, math.ceil(0.6 * total_samples))
    )

    parsed_soups = _ensure_soups(samples, soups)

    # Thu thập ứng viên selector tiêu đề
    candidate_selectors: set[str] = {"h1", "h2", "h3"}

    for soup in parsed_soups[:2]:
        for el in soup.find_all(["h1", "h2", "h3", "span", "div", "p"]):
            classes = el.get("class") or []
            if isinstance(classes, str):
                classes = [classes]
            el_id = el.get("id")

            # Gợi ý tiêu đề từ class / id
            all_tokens = list(classes) + ([el_id] if el_id else [])
            is_title_like = any(
                any(kw in t.lower() for kw in ("title", "chapter", "chap", "heading", "cha-hd", "entry-title"))
                for t in all_tokens
                if t
            )

            if is_title_like:
                if _is_safe_ident(el_id):
                    candidate_selectors.add(f"{el.name}#{el_id}")
                for cls in classes:
                    if _is_safe_ident(cls):
                        candidate_selectors.add(f"{el.name}.{cls}")

    results: list[TitleCandidate] = []

    for sel in candidate_selectors:
        extracted_titles: list[str] = []
        for soup in parsed_soups:
            try:
                el = soup.select_one(sel)
            except Exception:
                break
            if not el:
                continue

            text = el.get_text(strip=True)
            # Tiêu đề chương chuẩn thường từ 3 đến 200 ký tự
            if 3 <= len(text) <= 200:
                extracted_titles.append(text)

        hit_count = len(extracted_titles)
        if hit_count < effective_min_matches:
            continue

        distinct_count = len(set(extracted_titles))
        # Nếu tất cả các chương đều ra cùng 1 text cố định (vd: tên trang web 'Royal Road')
        # thì đó KHÔNG phải tiêu đề chương!
        if total_samples >= 2 and distinct_count <= 1:
            continue

        has_kw = any(_CHAPTER_KEYWORD_RE.search(t) for t in extracted_titles)

        # Chấm điểm
        score = (hit_count / total_samples) * 40.0
        # Tiêu đề chương phải biến đổi qua các chương
        if distinct_count >= 2:
            score += 30.0
        # Có từ khóa chương / số chương
        if has_kw:
            score += 20.0
        # Ưu tiên thẻ ngữ nghĩa h1 > h2 > h3
        if sel == "h1" or sel.startswith("h1."):
            score += 20.0
        elif sel == "h2" or sel.startswith("h2."):
            score += 10.0
        elif sel == "h3" or sel.startswith("h3."):
            score += 5.0

        results.append(
            TitleCandidate(
                selector=sel,
                hit_count=hit_count,
                total_samples=total_samples,
                sample_titles=extracted_titles,
                distinct_titles_count=distinct_count,
                has_chapter_keyword=has_kw,
                score=round(score, 2),
            )
        )

    results.sort(key=lambda x: (x.score, x.hit_count), reverse=True)
    return results[:top_k]


# ── Next-Link Candidate Discovery ─────────────────────────────────────────────


def find_next_candidates(
    samples: list[tuple[str, str]],
    soups: list[BeautifulSoup] | None = None,
) -> list[NextCandidate]:
    """Tìm và xếp hạng ứng viên điều hướng sang chương kế tiếp."""
    if not samples:
        return []

    total_samples = len(samples)
    parsed_soups = _ensure_soups(samples, soups)

    transitions: list[tuple[str, str, BeautifulSoup]] = []

    for i in range(total_samples - 1):
        curr_url, _ = samples[i]
        next_url, _ = samples[i + 1]
        transitions.append((curr_url, next_url, parsed_soups[i]))

    candidates: list[NextCandidate] = []

    # Chiến lược 1: Khớp thực tế theo Ground-Truth URL chuyển tiếp
    if transitions:
        total_transitions = len(transitions)
        candidate_selectors: set[str] = set()

        for curr_url, next_url, soup in transitions:
            norm_target = _normalize_url(next_url)

            for tag_name in ("a", "link"):
                for el in soup.find_all(tag_name):
                    href = el.get("href")
                    if not href:
                        continue
                    full_href = _normalize_url(urljoin(curr_url, href))
                    if full_href == norm_target:
                        rel = el.get("rel") or []
                        if isinstance(rel, str):
                            rel = [rel]
                        if "next" in rel:
                            candidate_selectors.add(f"{tag_name}[rel~='next']")
                            candidate_selectors.add("rel_next")

                        el_id = el.get("id")
                        if _is_safe_ident(el_id):
                            candidate_selectors.add(f"{tag_name}#{el_id}")
                            candidate_selectors.add(f"#{el_id}")

                        classes = el.get("class") or []
                        if isinstance(classes, str):
                            classes = [classes]
                        for c in classes:
                            if _is_safe_ident(c):
                                candidate_selectors.add(f"{tag_name}.{c}")

                        # Kiểm tra parent container (vd: div.nav-next a)
                        parent = el.parent
                        if isinstance(parent, Tag):
                            p_classes = parent.get("class") or []
                            if isinstance(p_classes, str):
                                p_classes = [p_classes]
                            for pc in p_classes:
                                if _is_safe_ident(pc):
                                    candidate_selectors.add(f"{parent.name}.{pc} {tag_name}")

        # Thử nghiệm từng selector qua tất cả transitions (sử dụng soup đã parse, O(1))
        for sel in candidate_selectors:
            if sel == "rel_next":
                matched_urls: list[str] = []
                for curr_url, next_url, soup in transitions:
                    el = soup.find(["link", "a"], rel=lambda r: r and "next" in (r if isinstance(r, list) else r.split()))
                    if el and el.get("href"):
                        resolved = urljoin(curr_url, el["href"])
                        if _normalize_url(resolved) == _normalize_url(next_url):
                            matched_urls.append(resolved)

                if matched_urls:
                    conf = len(matched_urls) / total_transitions
                    candidates.append(
                        NextCandidate(
                            selector=None,
                            nav_type="rel_next",
                            hit_count=len(matched_urls),
                            total_transitions=total_transitions,
                            resolved_urls=matched_urls,
                            confidence=round(conf, 2),
                        )
                    )
            else:
                matched_urls = []
                for curr_url, next_url, soup in transitions:
                    try:
                        el = soup.select_one(sel)
                    except Exception:
                        break
                    if el and el.get("href"):
                        resolved = urljoin(curr_url, el["href"])
                        if _normalize_url(resolved) == _normalize_url(next_url):
                            matched_urls.append(resolved)

                if matched_urls:
                    conf = len(matched_urls) / total_transitions
                    candidates.append(
                        NextCandidate(
                            selector=sel,
                            nav_type="selector",
                            hit_count=len(matched_urls),
                            total_transitions=total_transitions,
                            resolved_urls=matched_urls,
                            confidence=round(conf, 2),
                        )
                    )

    # Chiến lược 2: Heuristic detection
    # 2.1: Kiểm tra rel=next
    if not any(c.nav_type == "rel_next" for c in candidates):
        rel_hits = 0
        rel_urls: list[str] = []
        for (curr_url, _), soup in zip(samples, parsed_soups, strict=True):
            el = soup.find(["link", "a"], rel=lambda r: r and "next" in (r if isinstance(r, list) else r.split()))
            if el and el.get("href"):
                rel_hits += 1
                rel_urls.append(urljoin(curr_url, el["href"]))
        if rel_hits >= max(1, total_samples // 2):
            candidates.append(
                NextCandidate(
                    selector=None,
                    nav_type="rel_next",
                    hit_count=rel_hits,
                    total_transitions=total_samples,
                    resolved_urls=rel_urls,
                    confidence=0.85,
                )
            )

    # 2.2: Kiểm tra anchor text "Next / Chương sau"
    text_hits = 0
    text_urls: list[str] = []
    for (curr_url, _), soup in zip(samples, parsed_soups, strict=True):
        found_url = None
        for a in soup.find_all("a"):
            t = a.get_text(strip=True)
            if _NEXT_TEXT_RE.match(t) and a.get("href"):
                found_url = urljoin(curr_url, a["href"])
                break
        if found_url:
            text_hits += 1
            text_urls.append(found_url)
    if text_hits >= max(1, total_samples // 2):
        candidates.append(
            NextCandidate(
                selector=None,
                nav_type="anchor_text",
                hit_count=text_hits,
                total_transitions=total_samples,
                resolved_urls=text_urls,
                confidence=0.80,
            )
        )

    # 2.3: Kiểm tra slug_increment
    if total_samples >= 2:
        slug_matches = 0
        for i in range(total_samples - 1):
            curr_url = samples[i][0]
            next_url = samples[i + 1][0]
            m_curr = _SLUG_INCREMENT_RE.search(curr_url)
            m_next = _SLUG_INCREMENT_RE.search(next_url)
            if m_curr and m_next:
                try:
                    num_curr = int(m_curr.group(3))
                    num_next = int(m_next.group(3))
                    if num_next == num_curr + 1:
                        slug_matches += 1
                except ValueError:
                    pass
        if slug_matches >= max(1, (total_samples - 1) // 2):
            candidates.append(
                NextCandidate(
                    selector=None,
                    nav_type="slug_increment",
                    hit_count=slug_matches,
                    total_transitions=total_samples - 1,
                    resolved_urls=[s[0] for s in samples[1:]],
                    confidence=0.70,
                )
            )

    # Sắp xếp theo confidence desc, hit_count desc
    candidates.sort(key=lambda x: (x.confidence, x.hit_count), reverse=True)
    return candidates


# ── Repeated Lines Discovery ──────────────────────────────────────────────────


def find_repeated_lines(
    samples: list[tuple[str, str]],
    content_selector: str | None = None,
    min_appearances: int = 2,
    max_lines: int = 30,
    soups: list[BeautifulSoup] | None = None,
) -> list[str]:
    """Tìm các dòng văn bản lặp lại giữa nhiều chương mẫu (nghi là rác, quảng cáo, watermark)."""
    if len(samples) < min_appearances:
        return []

    parsed_soups = _ensure_soups(samples, soups)
    line_appearances: dict[str, set[int]] = defaultdict(set)

    for idx, soup in enumerate(parsed_soups):
        target_el = None
        if content_selector:
            try:
                target_el = soup.select_one(content_selector)
            except Exception:
                target_el = None

        if target_el is None:
            target_el = soup.body or soup

        raw_text = target_el.get_text()
        for line in raw_text.splitlines():
            line_clean = line.strip()
            # Bỏ qua dòng quá ngắn hoặc dòng toàn số/ký tự phân cách
            if len(line_clean) < 6:
                continue
            if line_clean.isdigit() or all(c in "-=_*~# " for c in line_clean):
                continue
            # Không đánh dấu tiêu đề chương thông thường là rác
            if _CHAPTER_KEYWORD_RE.match(line_clean) and len(line_clean) < 25:
                continue

            line_appearances[line_clean].add(idx)

    # Lọc các dòng xuất hiện ở >= min_appearances chương
    repeated = [
        (line, len(indices))
        for line, indices in line_appearances.items()
        if len(indices) >= min_appearances
    ]

    # Ưu tiên các dòng lặp lại ở hầu hết các chương, sau đó xếp theo độ dài
    repeated.sort(key=lambda item: (item[1], len(item[0])), reverse=True)

    return [line for line, _ in repeated[:max_lines]]


# ── Raw Titles Discovery ──────────────────────────────────────────────────────


def find_raw_titles(
    samples: list[tuple[str, str]],
    soups: list[BeautifulSoup] | None = None,
) -> list[str]:
    """Thu thập các tiêu đề thô từ thẻ <title>, og:title và <h1> từ các mẫu."""
    titles: list[str] = []
    seen: set[str] = set()
    parsed_soups = _ensure_soups(samples, soups)

    for soup in parsed_soups:
        candidates_raw: list[str] = []

        h1 = soup.find("h1")
        if h1:
            candidates_raw.append(h1.get_text(strip=True))

        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            candidates_raw.append(og_title["content"].strip())

        title_tag = soup.find("title")
        if title_tag:
            candidates_raw.append(title_tag.get_text(strip=True))

        for t in candidates_raw:
            if t and t not in seen and 3 <= len(t) <= 250:
                seen.add(t)
                titles.append(t)

    return titles


# ── Main Entry Point ──────────────────────────────────────────────────────────


def find_site_candidates(
    samples: list[tuple[str, str]],
    min_chars: int = 300,
) -> SiteCandidates:
    """Điểm vào chính: phân tích các chương mẫu và phát hiện toàn bộ ứng viên bằng code thuần."""
    # Parse một lần duy nhất cho toàn bộ các bước phát hiện
    soups = [BeautifulSoup(html, "lxml") for _, html in samples]

    content_candidates = find_content_candidates(samples, min_chars=min_chars, soups=soups)
    title_candidates = find_title_candidates(samples, soups=soups)
    next_candidates = find_next_candidates(samples, soups=soups)

    best_content = content_candidates[0].selector if content_candidates else None
    best_title = title_candidates[0].selector if title_candidates else None
    best_next = next_candidates[0].selector if next_candidates else None
    best_nav = next_candidates[0].nav_type if next_candidates else "selector"

    repeated_lines = find_repeated_lines(
        samples,
        content_selector=best_content,
        min_appearances=2 if len(samples) >= 3 else 1,
        soups=soups,
    )
    raw_titles = find_raw_titles(samples, soups=soups)

    return SiteCandidates(
        content_candidates=content_candidates,
        title_candidates=title_candidates,
        next_candidates=next_candidates,
        repeated_lines=repeated_lines,
        raw_titles=raw_titles,
        best_content_selector=best_content,
        best_title_selector=best_title,
        best_next_selector=best_next,
        best_nav_type=best_nav,
    )
