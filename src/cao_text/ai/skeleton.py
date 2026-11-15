"""Nén HTML thô thành DOM skeleton rút gọn phục vụ phân tích cấu trúc trang bằng AI."""
from __future__ import annotations

import logging
import re
from typing import Any

from bs4 import BeautifulSoup, Comment, Tag

logger = logging.getLogger(__name__)

# Các thẻ nội dung đa phương tiện / script không chứa thông tin cấu trúc văn bản hoặc điều hướng
DISCARD_TAGS = {
    "script",
    "style",
    "svg",
    "noscript",
    "canvas",
    "iframe",
    "video",
    "audio",
    "object",
    "embed",
    "link",
    "meta",
    "picture",
    "source",
    "track",
    "map",
    "area",
}

# Các thuộc tính cốt lõi cần giữ lại cho việc nhận diện selector
ALLOWED_ATTRS = {"id", "class", "role", "rel"}

# Nhận diện class bị làm rối (obfuscated base64/hash) hoặc gắn ID động từng đoạn văn
_HEX_HASH_RE = re.compile(r"[0-9a-fA-F]{16,}")
_RANDOM_TOKEN_RE = re.compile(r"^[A-Za-z0-9]{22,}$")

# Các thẻ inline trống rỗng (thường là icon sau khi xóa svg/font) cần dọn nếu không có chữ
_EMPTY_INLINE_TAGS = {"i", "span", "em", "b", "strong", "small", "u", "s", "sub", "sup"}


def _is_obfuscated_class(cls_name: str) -> bool:
    """Kiểm tra xem tên class có phải chuỗi hash/ngẫu nhiên sinh động theo từng thẻ hay không."""
    if _HEX_HASH_RE.search(cls_name):
        return True
    if _RANDOM_TOKEN_RE.match(cls_name) and any(c.isdigit() for c in cls_name):
        return True
    return False


def _filter_tag_attributes(tag: Tag) -> None:
    """Lọc bỏ các thuộc tính không cần thiết và loại bỏ các class bị làm rối của một thẻ HTML."""
    attrs_to_delete: list[str] = []
    for attr, val in list(tag.attrs.items()):
        if attr in ALLOWED_ATTRS:
            if attr == "class":
                raw_classes = val if isinstance(val, list) else str(val).split()
                clean_classes = [c for c in raw_classes if not _is_obfuscated_class(c)]
                if clean_classes:
                    tag.attrs["class"] = " ".join(clean_classes)
                else:
                    attrs_to_delete.append("class")
            continue
        if attr.startswith("aria-"):
            continue
        if tag.name in ("a", "link") and attr == "href":
            if isinstance(val, str) and len(val) > 120:
                tag.attrs[attr] = val[:120] + "..."
            continue
        if tag.name == "option" and attr in ("value", "selected"):
            continue
        attrs_to_delete.append(attr)

    for attr in attrs_to_delete:
        tag.attrs.pop(attr, None)


def _collapse_repeating_children(soup: BeautifulSoup, repeat_threshold: int = 4) -> None:
    """Duyệt cây DOM và gộp các thẻ con liên tiếp có cấu trúc tương tự nhau."""
    for parent in list(soup.find_all(True)):
        if parent.parent is None:
            continue
        child_tags = [c for c in parent.children if isinstance(c, Tag)]
        if len(child_tags) < repeat_threshold:
            continue

        groups: list[list[Tag]] = []
        current_group: list[Tag] = []
        current_sig: Any = None

        for child in child_tags:
            cls_val = child.get("class", [])
            classes = tuple(sorted(cls_val if isinstance(cls_val, list) else cls_val.split()))
            is_selected = "selected" in child.attrs
            rel_val = child.get("rel", [])
            rel = tuple(sorted(rel_val if isinstance(rel_val, list) else rel_val.split()))
            has_id = bool(child.get("id"))
            sig = (child.name, classes, is_selected, rel, has_id)
            if sig == current_sig:
                current_group.append(child)
            else:
                if current_group:
                    groups.append(current_group)
                current_group = [child]
                current_sig = sig
        if current_group:
            groups.append(current_group)

        for group in groups:
            if len(group) >= repeat_threshold:
                keep_first = 2
                keep_last = 1
                omitted = len(group) - (keep_first + keep_last)
                if omitted > 0:
                    tag_name = group[0].name
                    placeholder = soup.new_tag(tag_name)
                    placeholder["class"] = "skeleton-collapsed"
                    placeholder.string = f"... [{omitted} thẻ <{tag_name}> tương tự được gộp] ..."
                    group[keep_first - 1].insert_after(placeholder)
                    for item in group[keep_first : len(group) - keep_last]:
                        item.decompose()


def compress_dom_to_skeleton(
    html: str,
    *,
    max_chars: int = 15000,
    max_node_text: int = 80,
    repeat_threshold: int = 4,
) -> str:
    """Nén mã HTML thành một DOM skeleton rút gọn tối đa token nhưng giữ nguyên cấu trúc DOM.

    Các thao tác thực hiện:
        1. Loại bỏ các thẻ rác: script, style, svg, noscript, canvas, iframe, comments...
        2. Lọc bỏ các thuộc tính không cần thiết; chỉ giữ `id`, `class`, `rel`, `role`,
           `aria-*`, `href` (của thẻ <a>), `value`/`selected` (của thẻ <option>).
        3. Cắt ngắn chuỗi văn bản trong mỗi node xuống <= `max_node_text` ký tự.
        4. Gộp các node con lặp lại liên tiếp (>= `repeat_threshold`) thành các mẫu đại diện.
        5. Đảm bảo tổng độ dài chuỗi kết quả không vượt quá ngân sách `max_chars`.

    Args:
        html: Chuỗi HTML đầu vào cần nén.
        max_chars: Ngân sách ký tự tối đa của skeleton đầu ra.
        max_node_text: Độ dài ký tự tối đa cho văn bản của mỗi node đơn lẻ.
        repeat_threshold: Số lượng node con lặp lại liên tiếp tối thiểu để kích hoạt gộp.

    Returns:
        Chuỗi HTML skeleton đã được nén gọn gàng.
    """
    if not html or not html.strip():
        return ""

    soup = BeautifulSoup(html, "html.parser")

    # 1. Trích xuất thông tin quan trọng từ <head> (<title> và <link rel="next">) trước khi xóa
    head_title_str: str | None = None
    next_link_href: str | None = None
    head = soup.find("head")
    if head is not None:
        title_tag = head.find("title")
        if title_tag:
            head_title_str = title_tag.get_text(strip=True)
        for link_tag in head.find_all("link"):
            rel_val = link_tag.get("rel", [])
            rels = [r.lower() for r in (rel_val if isinstance(rel_val, list) else str(rel_val).split())]
            if "next" in rels and link_tag.get("href"):
                next_link_href = str(link_tag.get("href"))
                break
        head.decompose()

    # 2. Loại bỏ các thẻ rác
    for tag in soup.find_all(DISCARD_TAGS):
        tag.decompose()

    # Xóa các comment HTML <!-- ... -->
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    # Đưa <title> và <link rel="next"> vào đầu <body> nếu có
    container = soup.body if soup.body is not None else soup
    if next_link_href:
        new_link = soup.new_tag("link", rel="next", href=next_link_href[:120])
        container.insert(0, new_link)
    if head_title_str:
        new_title = soup.new_tag("title")
        new_title.string = head_title_str[:max_node_text]
        container.insert(0, new_title)

    # 3. Cắt ngắn văn bản của mỗi node và xóa khoảng trắng thừa
    for text_node in list(soup.find_all(string=True)):
        if isinstance(text_node, Comment):
            continue
        raw = str(text_node)
        cleaned = re.sub(r"\s+", " ", raw).strip()
        if not cleaned:
            text_node.extract()
            continue
        if len(cleaned) > max_node_text:
            cleaned = cleaned[:max_node_text].rstrip() + "..."
        text_node.replace_with(cleaned)

    # 4. Lọc và chuẩn hóa thuộc tính của từng tag (xóa cả class obfuscated trước khi gộp thẻ lặp)
    for tag in soup.find_all(True):
        _filter_tag_attributes(tag)

    # Dọn dẹp các thẻ inline rỗng (ví dụ <i class="icon"></i> không chứa chữ hay thẻ con)
    for tag in reversed(list(soup.find_all(True))):
        if tag.name in _EMPTY_INLINE_TAGS and not tag.get_text(strip=True) and not tag.find(True):
            if not tag.get("id"):
                tag.decompose()

    # 5. Gộp các node con lặp lại liên tiếp (ví dụ 100 đoạn <p> hay 500 mục <li>)
    _collapse_repeating_children(soup, repeat_threshold=repeat_threshold)

    # 6. Render kết quả và áp dụng trần max_chars (giữ cả phần đầu và phần cuối trang)
    target = soup.body if soup.body is not None else soup
    raw_output = str(target)
    cleaned_output = re.sub(r">\s+<", "><", raw_output).strip()

    if len(cleaned_output) > max_chars:
        marker = f"\n<!-- ... [DOM Skeleton đã được cắt bớt để bảo toàn giới hạn {max_chars} ký tự] -->\n"
        if max_chars <= len(marker) + 40:
            cleaned_output = cleaned_output[:max_chars]
        else:
            avail = max_chars - len(marker)
            head_budget = int(avail * 0.7)
            tail_budget = avail - head_budget

            head_part = cleaned_output[:head_budget]
            last_gt = head_part.rfind(">")
            if last_gt > head_budget // 2:
                head_part = head_part[: last_gt + 1]

            tail_part = cleaned_output[len(cleaned_output) - tail_budget :]
            first_lt = tail_part.find("<")
            if 0 <= first_lt < tail_budget // 2:
                tail_part = tail_part[first_lt:]

            cleaned_output = f"{head_part}{marker}{tail_part}"

    return cleaned_output
