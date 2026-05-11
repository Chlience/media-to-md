"""Utilities for deriving plain transcript text from SRT subtitles."""

from __future__ import annotations

import re
from pathlib import Path

_SRT_SEQUENCE_RE = re.compile(r"^\d+$")
_SRT_TIMING_RE = re.compile(
    r"^\d{1,3}:\d{2}:\d{2}[,.]\d{1,3}\s+-->\s+"
    r"\d{1,3}:\d{2}:\d{2}[,.]\d{1,3}(?:\s+.*)?$"
)


def srt_to_plain_text(content: str) -> str:
    """Strip SRT sequence and timing rows while preserving transcript text."""

    lines: list[str] = []
    previous_blank = False
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            if lines and not previous_blank:
                lines.append("")
                previous_blank = True
            continue
        if _SRT_SEQUENCE_RE.fullmatch(line):
            continue
        if _SRT_TIMING_RE.fullmatch(line):
            continue
        lines.append(line)
        previous_blank = False
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines).strip()


def write_plain_text_from_srt(srt_path: Path, txt_path: Path | None = None) -> Path:
    """Create a txt transcript next to an SRT by removing sequence/timing rows."""

    target = txt_path or srt_path.with_suffix(".txt")
    text = srt_to_plain_text(srt_path.read_text(encoding="utf-8", errors="replace"))
    target.write_text(text.rstrip() + ("\n" if text else ""), encoding="utf-8")
    return target


def derive_plain_text_from_srt_outputs(output_dir: Path) -> tuple[Path, ...]:
    """Generate txt files for every SRT file in an output directory."""

    if not output_dir.exists():
        return ()
    created: list[Path] = []
    for srt_path in sorted(output_dir.rglob("*.srt")):
        if not srt_path.is_file():
            continue
        created.append(write_plain_text_from_srt(srt_path))
    return tuple(created)
