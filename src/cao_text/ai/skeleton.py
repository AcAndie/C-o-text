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


def _filter_tag_attributes(tag: Tag) -> None:
    """Lọc bỏ các thuộc tính không cần thiết của một thẻ HTML."""
    attrs_to_delete: list[str] = []
    for attr, val in tag.attrs.items():
        if attr in ALLOWED_ATTRS:
            if attr == "class" and isinstance(val, list):
                tag.attrs[attr] = " ".join(val)
            continue
        if attr.startswith("aria-"):
            continue
        if tag.name == "a" and attr == "href":
            if isinstance(val, str) and len(val) > 120:
                tag.attrs[attr] = val[:120] + "..."
            continue
        if tag.name == "option" and attr in ("value", "selected"):
            continue
        attrs_to_delete.append(attr)

    for attr in attrs_to_delete:
        del tag.attrs[attr]


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

    # 1. Loại bỏ các thẻ rác
    for tag in soup.find_all(DISCARD_TAGS):
        tag.decompose()

    # Xóa các comment HTML <!-- ... -->
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    # 2. Xử lý phần thẻ <head>: chỉ giữ lại <title> nếu có
    head = soup.find("head")
    if head is not None:
        title = head.find("title")
        title_str = title.get_text(strip=True) if title else None
        head.decompose()
        if title_str and soup.body is not None:
            new_title = soup.new_tag("title")
            new_title.string = title_str[:max_node_text]
            soup.body.insert(0, new_title)

    # 3. Gộp các node con lặp lại liên tiếp (ví dụ 100 đoạn <p> hay 500 mục <li>)
    _collapse_repeating_children(soup, repeat_threshold=repeat_threshold)

    # 4. Lọc và chuẩn hóa thuộc tính của từng tag
    for tag in soup.find_all(True):
        _filter_tag_attributes(tag)

    # 5. Cắt ngắn văn bản của mỗi node
    for text_node in list(soup.find_all(string=True)):
        if isinstance(text_node, Comment):
            continue
        raw = str(text_node)
        cleaned = re.sub(r"\s+", " ", raw).strip()
        if not cleaned:
            text_node.replace_with("")
            continue
        if len(cleaned) > max_node_text:
            cleaned = cleaned[:max_node_text].rstrip() + "..."
        text_node.replace_with(cleaned)

    # 6. Render kết quả và áp dụng trần max_chars
    target = soup.body if soup.body is not None else soup
    raw_output = str(target)
    cleaned_output = re.sub(r">\s+<", "><", raw_output).strip()

    if len(cleaned_output) > max_chars:
        truncated = cleaned_output[:max_chars]
        last_bracket = truncated.rfind(">")
        if last_bracket > 0:
            truncated = truncated[: last_bracket + 1]
        cleaned_output = f"{truncated}\n<!-- ... [DOM Skeleton đã được cắt bớt để bảo toàn giới hạn {max_chars} ký tự] -->"

    return cleaned_output
