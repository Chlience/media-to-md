"""Post-process OpenDataLoader PDF outputs for product-facing Markdown.

OpenDataLoader JSON keeps page coordinates for text and image nodes.  The web
app uses those coordinates to remove text that falls inside image/picture
regions from the generated Markdown, so figure labels or OCR layers do not
pollute the text users copy into LLM prompts.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

IMAGE_TYPES = {"image", "picture", "figure", "chart"}
TEXT_TYPES = {"paragraph", "heading", "caption", "list item", "text"}
IMAGE_TEXT_OVERLAP_THRESHOLD = 0.6
FIGURE_NEIGHBORHOOD_LINE_LIMIT = 80
IMAGE_FOLLOWING_LINE_LIMIT = 40

FIGURE_CAPTION_RE = re.compile(r"^\s*(?:figure|fig\.?|图)\s*\d+[A-Za-z]?\s*[:：]", re.I)
TABLE_CAPTION_RE = re.compile(r"^\s*(?:table|tab\.?|表)\s*\d+[A-Za-z]?\s*[:：]", re.I)


MarkdownCleanupStrength = Literal["off", "conservative", "balanced", "aggressive"]


@dataclass(frozen=True)
class MarkdownImageTextFilterResult:
    files_processed: int = 0
    files_created: int = 0
    filtered_text_count: int = 0

    @property
    def changed(self) -> bool:
        return self.files_created > 0


def _cleanup_enabled(cleanup_strength: MarkdownCleanupStrength) -> bool:
    return cleanup_strength != "off"


def postprocess_opendataloader_markdown_outputs(
    output_dir: Path,
    *,
    overlap_threshold: float = IMAGE_TEXT_OVERLAP_THRESHOLD,
    cleanup_strength: MarkdownCleanupStrength = "balanced",
) -> MarkdownImageTextFilterResult:
    """Filter image-contained text from Markdown files next to ODL JSON files.

    The function is deliberately best-effort: invalid/missing JSON or Markdown
    files are ignored so a successful conversion is not failed by postprocess.
    Existing Markdown files are preserved; filtered copies are written as
    `*_clear.md` so users can download both raw and clean outputs.
    """

    if not output_dir.exists():
        return MarkdownImageTextFilterResult()

    if cleanup_strength == "off":
        return MarkdownImageTextFilterResult()

    rules = _markdown_cleanup_rule_groups(cleanup_strength)
    files_processed = 0
    files_created = 0
    filtered_text_count = 0
    for json_path in sorted(output_dir.rglob("*.json")):
        markdown_path = _matching_markdown_path(json_path)
        if markdown_path is None:
            continue
        stem = markdown_path.stem
        if stem.endswith("_clear"):
            continue
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        try:
            original = markdown_path.read_text(encoding="utf-8")
        except OSError:
            continue

        filtered_texts = _collect_image_texts(
            payload,
            overlap_threshold,
            include_descriptions=rules.descriptions,
            include_hidden_text=rules.hidden_text,
            include_bbox_overlap=rules.bbox_overlap,
            include_suspicious_fragments=rules.suspicious_json_short_fragments,
        )
        filtered = filter_markdown_image_text(
            original,
            filtered_texts,
            apply_markdown_neighborhood_pass=rules.markdown_neighborhood_pass,
        )
        files_processed += 1
        filtered_text_count += len(filtered_texts)
        clean_path = _clean_markdown_path(markdown_path)
        clean_path.write_text(filtered, encoding="utf-8")
        files_created += 1

    return MarkdownImageTextFilterResult(
        files_processed=files_processed,
        files_created=files_created,
        filtered_text_count=filtered_text_count,
    )


def filter_markdown_image_text(
    markdown: str,
    filtered_texts: set[str],
    *,
    apply_markdown_neighborhood_pass: bool = True,
) -> str:
    """Remove image-contained text and nearby visual debris from Markdown.

    OpenDataLoader does not always classify chart/diagram text as belonging to a
    figure.  Clean Markdown therefore removes exact JSON-derived targets from
    the whole document, then applies a Markdown neighborhood pass for short axis
    labels, legends, math glyph fragments, and diagram node labels that appear
    between prose/image references and figure captions.
    """

    normalized_targets = _normalized_filter_targets(filtered_texts)
    filtered = _remove_target_text(markdown, normalized_targets)
    if apply_markdown_neighborhood_pass:
        filtered = _remove_visual_noise_near_figures(filtered)
    return _collapse_blank_lines(filtered).strip() + "\n"


@dataclass(frozen=True)
class MarkdownCleanupRuleGroups:
    descriptions: bool
    hidden_text: bool
    bbox_overlap: bool
    suspicious_json_short_fragments: bool
    markdown_neighborhood_pass: bool
    aggressive_extra: bool = False


def _markdown_cleanup_rule_groups(
    cleanup_strength: MarkdownCleanupStrength,
) -> MarkdownCleanupRuleGroups:
    if cleanup_strength == "off":
        return MarkdownCleanupRuleGroups(
            descriptions=False,
            hidden_text=False,
            bbox_overlap=False,
            suspicious_json_short_fragments=False,
            markdown_neighborhood_pass=False,
            aggressive_extra=False,
        )
    if cleanup_strength == "conservative":
        return MarkdownCleanupRuleGroups(
            descriptions=True,
            hidden_text=True,
            bbox_overlap=True,
            suspicious_json_short_fragments=False,
            markdown_neighborhood_pass=False,
            aggressive_extra=False,
        )
    return MarkdownCleanupRuleGroups(
        descriptions=True,
        hidden_text=True,
        bbox_overlap=True,
        suspicious_json_short_fragments=True,
        markdown_neighborhood_pass=True,
        aggressive_extra=False,
    )


def _resolve_cleanup_config(cleanup_strength: MarkdownCleanupStrength) -> dict[str, Any]:
    """Normalize cleanup config and map `aggressive` as balanced placeholder."""

    rules = _markdown_cleanup_rule_groups(cleanup_strength)
    return {
        "enabled": cleanup_strength != "off",
        "rules": rules,
        "aggressive_placeholder": cleanup_strength == "aggressive",
    }


def _normalized_filter_targets(filtered_texts: set[str]) -> set[str]:
    targets: set[str] = set()
    for text in filtered_texts:
        for candidate in (text, _markdown_plain_text(text)):
            normalized = _normalize_text(candidate)
            if normalized:
                targets.add(normalized)
    return targets


def _remove_target_text(markdown: str, normalized_targets: set[str]) -> str:
    if not normalized_targets:
        return markdown

    parts = re.split(r"(\n\s*\n)", markdown)
    kept: list[str] = []
    for part in parts:
        if not part:
            continue
        if part.strip() == "":
            if kept and kept[-1].strip():
                kept.append(part)
            continue

        plain = _markdown_plain_text(part)
        if not _is_protected_markdown_block(part) and _text_matches_any_target(
            plain, normalized_targets
        ):
            continue

        cleaned_lines = [
            line
            for line in part.splitlines(keepends=True)
            if _is_protected_markdown_line(line)
            or not _text_matches_any_target(_markdown_plain_text(line), normalized_targets)
        ]
        if len(cleaned_lines) != len(part.splitlines(keepends=True)):
            cleaned = "".join(cleaned_lines)
            if cleaned.strip():
                kept.append(cleaned)
            continue

        kept.append(part)

    return "".join(kept)


def _matching_markdown_path(json_path: Path) -> Path | None:
    base = json_path.with_suffix("")
    if base.is_file():
        return base
    for suffix in (".md", ".markdown"):
        candidate = base.with_suffix(suffix)
        if candidate.is_file():
            return candidate
    return None


def _clean_markdown_path(markdown_path: Path) -> Path:
    suffix = "".join(markdown_path.suffixes[-1:])
    stem = markdown_path.name[: -len(suffix)] if suffix else markdown_path.name
    return markdown_path.with_name(f"{stem}_clear.md")


def _collect_image_texts(
    payload: Any,
    overlap_threshold: float,
    *,
    include_descriptions: bool = True,
    include_hidden_text: bool = True,
    include_bbox_overlap: bool = True,
    include_suspicious_fragments: bool = True,
) -> set[str]:
    image_boxes = _collect_image_boxes(payload)
    filtered: set[str] = set()
    for node in _walk_json(payload):
        if not isinstance(node, dict):
            continue
        node_type = _node_type(node)
        description = node.get("description")
        if include_descriptions and node_type in IMAGE_TYPES and isinstance(description, str):
            filtered.add(description)

        content = node.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        if _is_protected_json_text_node(node_type, content):
            continue
        if include_hidden_text and (
            _truthy(node.get("hidden text")) or _truthy(node.get("hidden_text"))
        ):
            filtered.add(content)
            continue
        if node_type not in TEXT_TYPES:
            continue
        if include_suspicious_fragments and _is_suspicious_json_short_fragment(
            node_type, content
        ):
            filtered.add(content)
            continue
        if not include_bbox_overlap:
            continue
        page = _node_page(node)
        bbox = _node_bbox(node)
        if page is None or bbox is None:
            continue
        if include_bbox_overlap and any(
            _overlap_ratio(bbox, image_bbox) >= overlap_threshold
            for image_bbox in image_boxes.get(page, [])
        ):
            filtered.add(content)
    return filtered


def _collect_image_boxes(payload: Any) -> dict[int, list[tuple[float, float, float, float]]]:
    boxes: dict[int, list[tuple[float, float, float, float]]] = {}
    for node in _walk_json(payload):
        if not isinstance(node, dict) or _node_type(node) not in IMAGE_TYPES:
            continue
        page = _node_page(node)
        bbox = _node_bbox(node)
        if page is not None and bbox is not None:
            boxes.setdefault(page, []).append(bbox)
    return boxes


def _is_suspicious_json_short_fragment(node_type: str, content: str) -> bool:
    """Return true for JSON text nodes that look like visual/OCR fragments.

    This intentionally runs globally, not only near Markdown image references,
    because OpenDataLoader may emit chart labels, axes, and diagram nodes as
    ordinary paragraph/text nodes without reliable figure relationships.
    """

    plain = _markdown_plain_text(content)
    if not plain or _is_figure_caption(plain) or _is_table_caption(plain):
        return False
    if node_type == "heading":
        return False
    if _looks_like_prose_sentence(plain):
        return False
    if _is_numeric_symbol_fragment(plain):
        return True
    if _contains_visual_math_glyph(plain):
        return True
    if _is_chart_or_diagram_label(plain):
        return True
    if _is_short_uppercase_fragment(plain):
        return True
    if _is_short_orphan_word_fragment(plain):
        return True
    return _is_short_unpunctuated_fragment(plain) and _has_visual_signal(plain)


def _walk_json(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _node_type(node: dict[str, Any]) -> str:
    return str(node.get("type") or "").strip().lower()


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _node_page(node: dict[str, Any]) -> int | None:
    value = node.get("page number", node.get("page_number", node.get("page")))
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _node_bbox(node: dict[str, Any]) -> tuple[float, float, float, float] | None:
    return _parse_bbox(node.get("bounding box", node.get("bounding_box", node.get("bbox"))))


def _parse_bbox(value: Any) -> tuple[float, float, float, float] | None:
    if isinstance(value, (list, tuple)) and len(value) == 4:
        try:
            return tuple(float(item) for item in value)  # type: ignore[return-value]
        except (TypeError, ValueError):
            return None
    if not isinstance(value, dict):
        return None
    for keys in (("x0", "y0", "x1", "y1"), ("left", "top", "right", "bottom")):
        if all(key in value for key in keys):
            try:
                return tuple(float(value[key]) for key in keys)  # type: ignore[return-value]
            except (TypeError, ValueError):
                return None
    if all(key in value for key in ("x", "y", "width", "height")):
        try:
            x = float(value["x"])
            y = float(value["y"])
            return (x, y, x + float(value["width"]), y + float(value["height"]))
        except (TypeError, ValueError):
            return None
    return None


def _area(bbox: tuple[float, float, float, float]) -> float:
    x0, y0, x1, y1 = bbox
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def _overlap_ratio(
    inner: tuple[float, float, float, float],
    outer: tuple[float, float, float, float],
) -> float:
    ix0 = max(inner[0], outer[0])
    iy0 = max(inner[1], outer[1])
    ix1 = min(inner[2], outer[2])
    iy1 = min(inner[3], outer[3])
    base = _area(inner)
    if base <= 0:
        return 0.0
    return _area((ix0, iy0, ix1, iy1)) / base


def _remove_visual_noise_near_figures(markdown: str) -> str:
    lines = markdown.splitlines()
    remove_indexes: set[int] = set()

    for index, line in enumerate(lines):
        if _is_figure_caption(line):
            _mark_preceding_visual_noise(lines, index, remove_indexes)
        if _contains_markdown_image(line):
            _mark_following_image_noise(lines, index, remove_indexes)

    if not remove_indexes:
        return markdown

    return "\n".join(
        line for index, line in enumerate(lines) if index not in remove_indexes
    )


def _is_protected_markdown_block(markdown: str) -> bool:
    return any(_is_protected_markdown_line(line) for line in markdown.splitlines())


def _is_protected_markdown_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    return (
        _contains_markdown_image(stripped)
        or _is_figure_caption(stripped)
        or _is_table_caption(stripped)
        or bool(re.match(r"^#{1,6}\s+\S", stripped))
    )


def _is_protected_json_text_node(node_type: str, content: str) -> bool:
    plain = _markdown_plain_text(content)
    return node_type == "heading" or _is_figure_caption(plain) or _is_table_caption(plain)


def _mark_preceding_visual_noise(
    lines: list[str], caption_index: int, remove_indexes: set[int]
) -> None:
    seen_visual = False
    start = max(-1, caption_index - FIGURE_NEIGHBORHOOD_LINE_LIMIT - 1)
    for index in range(caption_index - 1, start, -1):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            if seen_visual:
                remove_indexes.add(index)
            continue
        if _is_visual_boundary_line(line):
            break
        if _is_removable_visual_fragment(line):
            remove_indexes.add(index)
            seen_visual = True
            continue
        if seen_visual and _is_short_unpunctuated_fragment(line):
            remove_indexes.add(index)
            continue
        break


def _mark_following_image_noise(
    lines: list[str], image_index: int, remove_indexes: set[int]
) -> None:
    seen_visual = False
    end = min(len(lines), image_index + IMAGE_FOLLOWING_LINE_LIMIT + 1)
    for index in range(image_index + 1, end):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            if seen_visual:
                remove_indexes.add(index)
            continue
        if _is_figure_caption(line):
            break
        if _is_visual_boundary_line(line):
            break
        if _is_removable_visual_fragment(line) or _is_short_unpunctuated_fragment(line):
            remove_indexes.add(index)
            seen_visual = True
            continue
        break


def _is_visual_boundary_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if _contains_markdown_image(stripped):
        return True
    if _is_figure_caption(stripped) or _is_table_caption(stripped):
        return True
    if re.match(r"^#{1,6}\s+\S", stripped):
        return True
    if stripped.startswith("```") or re.fullmatch(r"[-*_]{3,}", stripped):
        return True
    if stripped.startswith("|") or stripped.count("|") >= 2:
        return True
    if re.match(r"^(?:[-*+]|\d+[.)]|[•●])\s+", stripped) and len(stripped) > 30:
        return True
    return _looks_like_prose_sentence(stripped)


def _is_removable_visual_fragment(line: str) -> bool:
    plain = _markdown_plain_text(line)
    if not plain or _is_figure_caption(plain) or _is_table_caption(plain):
        return False
    if _contains_markdown_image(line) or _looks_like_prose_sentence(plain):
        return False
    if _is_numeric_symbol_fragment(plain):
        return True
    if _contains_visual_math_glyph(plain):
        return True
    if _is_chart_or_diagram_label(plain):
        return True
    if _is_short_uppercase_fragment(plain):
        return True
    return _is_short_unpunctuated_fragment(plain) and _has_visual_signal(plain)


def _is_short_unpunctuated_fragment(line: str) -> bool:
    plain = _markdown_plain_text(line)
    if not plain or _looks_like_prose_sentence(plain):
        return False
    if len(plain) > 48:
        return False
    if re.search(r"[.!?。！？;；:]$", plain):
        return False
    return len(re.findall(r"[\w\u4e00-\u9fff]+", plain, flags=re.UNICODE)) <= 6


def _looks_like_prose_sentence(text: str) -> bool:
    plain = _normalize_text(text)
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", plain)
    if len(plain) >= 80 and len(words) >= 8:
        return True
    if len(words) >= 6 and re.search(r"[.!?。！？;；]$", plain):
        return True
    return bool(
        len(plain) >= 55
        and len(words) >= 7
        and re.search(r"\b(?:the|and|of|to|in|with|for|that|this|we|our)\b", plain, re.I)
    )


def _is_numeric_symbol_fragment(text: str) -> bool:
    return bool(
        re.fullmatch(r"[\d\s.,:%+\-−–—·•*/_|()[\]{}<>≈=✓×#]+", text)
        and re.search(r"[\d≈=✓×#]", text)
    )


def _contains_visual_math_glyph(text: str) -> bool:
    return any(character in text for character in "≈✓→←↑↓↔𝑎𝑒𝑓𝑔ℎ𝑙𝑚𝑡①②③")


def _is_chart_or_diagram_label(text: str) -> bool:
    normalized = _normalize_text(text).lower()
    labels = {
        "accept length",
        "concat",
        "data scale",
        "decoder layer",
        "decoder layers",
        "embedding",
        "fc layer",
        "lm head",
        "speedup",
        "target model",
    }
    if normalized in labels:
        return True
    return bool(re.fullmatch(r"eagle\s*-?\s*\d|eagle-?\d|eagle3", normalized))


def _is_short_uppercase_fragment(text: str) -> bool:
    letters = re.findall(r"[A-Za-z]", text)
    if not letters or len(text) > 48:
        return False
    uppercase = sum(1 for letter in letters if letter.isupper())
    return uppercase / len(letters) >= 0.8 and len(letters) >= 3


def _is_short_orphan_word_fragment(text: str) -> bool:
    normalized = _normalize_text(text)
    if len(normalized) > 8:
        return False
    return bool(re.fullmatch(r"[a-z]{2,6}\.?", normalized))


def _has_visual_signal(text: str) -> bool:
    return bool(
        re.search(r"\d|[-−–—_/|#]|[(){}\[\]<>]|^[A-Z][A-Za-z]?$", text)
        or len(text) <= 12
    )


def _is_figure_caption(text: str) -> bool:
    return bool(FIGURE_CAPTION_RE.match(text.strip()))


def _is_table_caption(text: str) -> bool:
    return bool(TABLE_CAPTION_RE.match(text.strip()))


def _contains_markdown_image(text: str) -> bool:
    return bool(re.search(r"!\[[^\]]*]\([^)]+\)", text))


def _markdown_plain_text(markdown: str) -> str:
    text = re.sub(r"!\[[^\]]*]\([^)]+\)", " ", markdown)
    text = re.sub(r"\[[^\]]+]\([^)]+\)", lambda match: match.group(0).split("]")[0][1:], text)
    text = re.sub(r"[`*_~>#|\\-]+", " ", text)
    return _normalize_text(text)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _text_matches_any_target(plain_text: str, targets: set[str]) -> bool:
    plain = _normalize_text(plain_text)
    if not plain:
        return False
    for target in targets:
        if plain == target:
            return True
        if len(plain) < 3 or len(target) < 3:
            continue
        if len(target) >= 12 and target in plain and len(target) / max(len(plain), 1) >= 0.45:
            return True
        if len(plain) >= 12 and plain in target and len(plain) / max(len(target), 1) >= 0.45:
            return True
    return False


def _collapse_blank_lines(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text)
