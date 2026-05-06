from __future__ import annotations

import json
from pathlib import Path

from app.opendataloader_pdf_postprocess import (
    filter_markdown_image_text,
    postprocess_opendataloader_markdown_outputs,
)


def test_filter_markdown_image_text_preserves_image_reference_and_body_text():
    markdown = """# Title

Body paragraph remains.

![image](paper_images/figure1.png)
TEXT INSIDE FIGURE
*A generated description of the visual figure.*

Final paragraph remains.
"""

    filtered = filter_markdown_image_text(
        markdown,
        {"TEXT INSIDE FIGURE", "A generated description of the visual figure."},
    )

    assert "Body paragraph remains." in filtered
    assert "Final paragraph remains." in filtered
    assert "![image](paper_images/figure1.png)" in filtered
    assert "TEXT INSIDE FIGURE" not in filtered
    assert "generated description" not in filtered


def test_filter_markdown_removes_chart_axis_block_before_figure_caption():
    markdown = """# Abstract

The sequential nature of modern LLMs makes them expensive and slow.

4.4
4.2
Speedup
4.0
3.8
3.6
3.4
3.2
1
2
EAGLE -2
-2
EAGLE3
3
4
8
6.0
Accept length
5.5
5.0
4.5
4.0
1
2
EAGLE -2
-2
EAGLE3
3
4
8
Figure 1: Scaling law evaluated on the MT-bench using LLaMA-Instruct 3.1 8B.

# 1 Introduction

Modern Large Language Models are being applied to more domains.
"""

    filtered = filter_markdown_image_text(markdown, set())

    assert "# Abstract" in filtered
    assert "sequential nature of modern LLMs" in filtered
    assert "Figure 1: Scaling law evaluated" in filtered
    assert "# 1 Introduction" in filtered
    assert "Modern Large Language Models" in filtered
    assert "\nSpeedup\n" not in filtered
    assert "Accept length" not in filtered
    assert "EAGLE3" not in filtered
    assert "4.4" not in filtered


def test_filter_markdown_removes_diagram_fragments_before_figure_caption():
    markdown = """The input to EAGLE-3 is explained below.

≈
𝑓
𝑙
𝑓 #3%
𝑡 #$0
③
LM Head
Decoder Layers
Concat
Embedding
Target Model
Figure 5: Diagram of the EAGLE-3 inference pipeline.

# 3 EAGLE-3

In this section, we provide a detailed description.
"""

    filtered = filter_markdown_image_text(markdown, set())

    assert "input to EAGLE-3 is explained" in filtered
    assert "Figure 5: Diagram" in filtered
    assert "# 3 EAGLE-3" in filtered
    assert "detailed description" in filtered
    assert "LM Head" not in filtered
    assert "Decoder Layers" not in filtered
    assert "𝑓" not in filtered
    assert "≈" not in filtered


def test_filter_markdown_removes_unmatched_text_after_image_reference():
    markdown = """Body paragraph remains.

![image](images/figure.png)

TEXT INSIDE FIGURE
Speedup
4.4

Figure 2: Speedup ratios of different methods.

Final paragraph remains.
"""

    filtered = filter_markdown_image_text(markdown, set())

    assert "Body paragraph remains." in filtered
    assert "![image](images/figure.png)" in filtered
    assert "Figure 2: Speedup ratios" in filtered
    assert "Final paragraph remains." in filtered
    assert "TEXT INSIDE FIGURE" not in filtered
    assert "\nSpeedup\n" not in filtered
    assert "4.4" not in filtered


def test_postprocess_removes_text_inside_image_bbox_from_markdown(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    (output / "paper.md").write_text(
        """# Paper

Visible body text.

![image](paper_images/image1.png)

FIGURE LABEL

Hidden OCR text
""",
        encoding="utf-8",
    )
    (output / "paper.json").write_text(
        json.dumps(
            {
                "kids": [
                    {
                        "type": "paragraph",
                        "page number": 1,
                        "bounding box": [20, 20, 180, 50],
                        "content": "Visible body text.",
                    },
                    {
                        "type": "image",
                        "page number": 1,
                        "bounding box": [100, 100, 300, 300],
                        "source": "paper_images/image1.png",
                    },
                    {
                        "type": "paragraph",
                        "page number": 1,
                        "bounding box": [120, 140, 240, 160],
                        "content": "FIGURE LABEL",
                    },
                    {
                        "type": "paragraph",
                        "page number": 1,
                        "bounding box": [20, 340, 180, 360],
                        "hidden text": True,
                        "content": "Hidden OCR text",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    result = postprocess_opendataloader_markdown_outputs(output)

    original = (output / "paper.md").read_text(encoding="utf-8")
    filtered = (output / "paper_clear.md").read_text(encoding="utf-8")
    assert result.files_created == 1
    assert result.filtered_text_count == 2
    assert "FIGURE LABEL" in original
    assert "Hidden OCR text" in original
    assert "Visible body text." in filtered
    assert "![image](paper_images/image1.png)" in filtered
    assert "FIGURE LABEL" not in filtered
    assert "Hidden OCR text" not in filtered


def test_postprocess_skip_already_clear_paper_clear_source(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    raw_markdown = "Body text.\n\nFIGURE LABEL\n"
    source = output / "paper_clear.md"
    source.write_text(raw_markdown, encoding="utf-8")
    (output / "paper_clear.json").write_text(
        json.dumps(
            {
                "kids": [
                    {
                        "type": "paragraph",
                        "page number": 1,
                        "bounding box": [120, 140, 220, 160],
                        "content": "FIGURE LABEL",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    result = postprocess_opendataloader_markdown_outputs(output)

    assert result.files_created == 0
    assert source.read_text(encoding="utf-8") == raw_markdown
    assert (output / "paper_clear.md").is_file()
    assert not (output / "paper_clear_clear.md").exists()


def test_postprocess_generates_clear_markdown_for_paper_markdown_source(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    (output / "paper.markdown").write_text("Body text.\n", encoding="utf-8")
    (output / "paper.markdown.json").write_text(
        json.dumps(
            {
                "kids": [
                    {
                        "type": "paragraph",
                        "page number": 1,
                        "content": "Body text.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = postprocess_opendataloader_markdown_outputs(output)
    assert result.files_created == 1
    assert result.files_processed == 1
    assert (output / "paper_clear.md").is_file()


def test_postprocess_off_creates_no_markdown_clear(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    (output / "paper.md").write_text("Body text.\n", encoding="utf-8")
    (output / "paper.json").write_text(json.dumps({"kids": []}), encoding="utf-8")

    result = postprocess_opendataloader_markdown_outputs(
        output, cleanup_strength="off"
    )
    clean = output / "paper_clear.md"

    assert result.files_created == 0
    assert result.files_processed == 0
    assert not clean.is_file()


def test_conservative_removes_image_descriptions_but_keeps_suspicious_fragments(tmp_path):
    output_balanced = tmp_path / "balanced"
    output_conservative = tmp_path / "conservative"
    output_balanced.mkdir()
    output_conservative.mkdir()

    def _seed(target: Path) -> None:
        target.mkdir(exist_ok=True)
        (target / "paper.md").write_text(
            """Body text.

![image](paper_images/image1.png)

Speedup
4.4
""",
            encoding="utf-8",
        )
        (target / "paper.json").write_text(
            json.dumps(
                {
                    "kids": [
                        {
                            "type": "image",
                            "page number": 1,
                            "bounding box": [100, 100, 300, 300],
                            "description": "A generated description of the visual figure.",
                        },
                        {
                            "type": "paragraph",
                            "page number": 1,
                            "content": "4.4",
                        },
                        {
                            "type": "paragraph",
                            "page number": 1,
                            "bounding box": [120, 120, 220, 140],
                            "content": "FIGURE LABEL",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )

    _seed(output_balanced)
    _seed(output_conservative)

    balanced = postprocess_opendataloader_markdown_outputs(output_balanced)
    conservative = postprocess_opendataloader_markdown_outputs(
        output_conservative, cleanup_strength="conservative"
    )
    balanced_filtered = (output_balanced / "paper_clear.md").read_text(
        encoding="utf-8"
    )
    conservative_filtered = (output_conservative / "paper_clear.md").read_text(
        encoding="utf-8"
    )

    assert balanced.files_created == 1
    assert conservative.files_created == 1
    assert "4.4" not in balanced_filtered
    assert "FIGURE LABEL" not in balanced_filtered
    assert "4.4" in conservative_filtered
    assert "FIGURE LABEL" not in conservative_filtered


def test_postprocess_removes_json_short_fragments_without_markdown_figure_context(
    tmp_path,
):
    output = tmp_path / "output"
    output.mkdir()
    (output / "paper.md").write_text(
        """# Abstract

The sequential nature of modern LLMs makes them expensive and slow.

Speedup

4.4

EAGLE3

LM Head

Figure 1: Scaling law evaluated on MT-bench.

# 1 Introduction

Modern Large Language Models are being applied to more domains.
""",
        encoding="utf-8",
    )
    (output / "paper.json").write_text(
        json.dumps(
            {
                "kids": [
                    {
                        "type": "heading",
                        "page number": 1,
                        "content": "Abstract",
                    },
                    {
                        "type": "paragraph",
                        "page number": 1,
                        "content": (
                            "The sequential nature of modern LLMs makes "
                            "them expensive and slow."
                        ),
                    },
                    {
                        "type": "paragraph",
                        "page number": 1,
                        "content": "Speedup",
                    },
                    {
                        "type": "paragraph",
                        "page number": 1,
                        "content": "4.4",
                    },
                    {
                        "type": "text",
                        "page number": 1,
                        "content": "EAGLE3",
                    },
                    {
                        "type": "paragraph",
                        "page number": 1,
                        "content": "LM Head",
                    },
                    {
                        "type": "caption",
                        "page number": 1,
                        "content": "Figure 1: Scaling law evaluated on MT-bench.",
                    },
                    {
                        "type": "heading",
                        "page number": 1,
                        "content": "1 Introduction",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    result = postprocess_opendataloader_markdown_outputs(output)

    filtered = (output / "paper_clear.md").read_text(encoding="utf-8")
    assert result.filtered_text_count == 4
    assert "# Abstract" in filtered
    assert "sequential nature of modern LLMs" in filtered
    assert "Figure 1: Scaling law evaluated" in filtered
    assert "# 1 Introduction" in filtered
    assert "\nSpeedup\n" not in filtered
    assert "4.4" not in filtered
    assert "EAGLE3" not in filtered
    assert "LM Head" not in filtered


def test_postprocess_preserves_protected_lines_even_when_json_overlaps_image(
    tmp_path,
):
    output = tmp_path / "output"
    output.mkdir()
    (output / "paper.md").write_text(
        """# Figure Findings

![image](paper_images/image1.png)

Figure 1: Scaling law evaluated on MT-bench.

Table 1: Speedup ratios.

FIGURE LABEL

Normal paragraph stays.
""",
        encoding="utf-8",
    )
    (output / "paper.json").write_text(
        json.dumps(
            {
                "kids": [
                    {
                        "type": "image",
                        "page number": 1,
                        "bounding box": [100, 100, 300, 300],
                    },
                    {
                        "type": "heading",
                        "page number": 1,
                        "bounding box": [120, 120, 260, 140],
                        "content": "Figure Findings",
                    },
                    {
                        "type": "caption",
                        "page number": 1,
                        "bounding box": [120, 145, 260, 165],
                        "content": "Figure 1: Scaling law evaluated on MT-bench.",
                    },
                    {
                        "type": "caption",
                        "page number": 1,
                        "bounding box": [120, 170, 260, 190],
                        "content": "Table 1: Speedup ratios.",
                    },
                    {
                        "type": "paragraph",
                        "page number": 1,
                        "bounding box": [120, 195, 260, 215],
                        "content": "FIGURE LABEL",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    result = postprocess_opendataloader_markdown_outputs(output)

    filtered = (output / "paper_clear.md").read_text(encoding="utf-8")
    assert result.filtered_text_count == 1
    assert "# Figure Findings" in filtered
    assert "![image](paper_images/image1.png)" in filtered
    assert "Figure 1: Scaling law evaluated" in filtered
    assert "Table 1: Speedup ratios." in filtered
    assert "Normal paragraph stays." in filtered
    assert "FIGURE LABEL" not in filtered


def test_postprocess_removes_single_char_and_markup_sensitive_json_fragments(
    tmp_path,
):
    output = tmp_path / "output"
    output.mkdir()
    visual_fragments = [
        "…",
        "𝑓",
        "𝑓 #3%",
        "𝑎 2 #$%",
        "ers.",
        "≈",
        "𝑙 #-.+/",
        "𝑡 #$(",
        "#$(",
        "+",
    ]
    (output / "paper.md").write_text(
        "\n".join(
            [
                "# Body",
                "",
                "This normal paragraph should stay.",
                "",
                *visual_fragments,
                "",
                "Another normal paragraph should stay.",
            ]
        ),
        encoding="utf-8",
    )
    (output / "paper.json").write_text(
        json.dumps(
            {
                "kids": [
                    {
                        "type": "paragraph",
                        "page number": 1,
                        "content": "This normal paragraph should stay.",
                    },
                    *[
                        {
                            "type": "paragraph",
                            "page number": 1,
                            "content": fragment,
                        }
                        for fragment in visual_fragments
                    ],
                    {
                        "type": "paragraph",
                        "page number": 1,
                        "content": "Another normal paragraph should stay.",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    result = postprocess_opendataloader_markdown_outputs(output)

    filtered = (output / "paper_clear.md").read_text(encoding="utf-8")
    assert result.filtered_text_count == len(visual_fragments)
    assert "This normal paragraph should stay." in filtered
    assert "Another normal paragraph should stay." in filtered
    for fragment in visual_fragments:
        assert fragment not in filtered


def test_postprocess_strength_conservative_skips_json_only_short_fragment_filtering(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    (output / "paper.md").write_text(
        """# Title

EAGLE3
4.4

Figure 1: Scaling law evaluated.

Normal paragraph.
""",
        encoding="utf-8",
    )
    (output / "paper.json").write_text(
        json.dumps(
            {
                "kids": [
                    {
                        "type": "text",
                        "page number": 1,
                        "content": "EAGLE3",
                    },
                    {
                        "type": "paragraph",
                        "page number": 1,
                        "content": "4.4",
                    },
                    {
                        "type": "paragraph",
                        "page number": 1,
                        "content": "Normal paragraph.",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    result = postprocess_opendataloader_markdown_outputs(
        output, cleanup_strength="conservative"
    )

    filtered = (output / "paper_clear.md").read_text(encoding="utf-8")
    assert result.files_created == 1
    assert "4.4" in filtered
    assert "EAGLE3" in filtered
    assert "Normal paragraph." in filtered


def test_postprocess_strength_balanced_removes_json_only_short_fragment_filtering(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    (output / "paper.md").write_text(
        """# Title

EAGLE3
4.4

Figure 1: Scaling law evaluated.

Normal paragraph.
""",
        encoding="utf-8",
    )
    (output / "paper.json").write_text(
        json.dumps(
            {
                "kids": [
                    {
                        "type": "text",
                        "page number": 1,
                        "content": "EAGLE3",
                    },
                    {
                        "type": "paragraph",
                        "page number": 1,
                        "content": "4.4",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    result = postprocess_opendataloader_markdown_outputs(
        output, cleanup_strength="balanced"
    )

    filtered = (output / "paper_clear.md").read_text(encoding="utf-8")
    assert result.files_created == 1
    assert "EAGLE3" not in filtered
    assert "4.4" not in filtered
    assert "Normal paragraph." in filtered
    assert "# Title" in filtered


def test_postprocess_strength_aggressive_matches_balanced_placeholder_by_default(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    (output / "paper.md").write_text(
        """# Title\n\nSpeedup\n4.4\n\nFigure 1: Scaling law evaluated.\n\nNormal paragraph.\n""",
        encoding="utf-8",
    )
    (output / "paper.json").write_text(
        json.dumps(
            {
                "kids": [
                    {"type": "text", "page number": 1, "content": "Speedup"},
                    {"type": "text", "page number": 1, "content": "4.4"},
                ]
            }
        ),
        encoding="utf-8",
    )

    balanced = postprocess_opendataloader_markdown_outputs(
        output, cleanup_strength="balanced"
    )
    balanced_text = (output / "paper_clear.md").read_text(encoding="utf-8")

    output = tmp_path / "output2"
    output.mkdir()
    (output / "paper.md").write_text(
        """# Title\n\nSpeedup\n4.4\n\nFigure 1: Scaling law evaluated.\n\nNormal paragraph.\n""",
        encoding="utf-8",
    )
    (output / "paper.json").write_text(
        json.dumps(
            {
                "kids": [
                    {"type": "text", "page number": 1, "content": "Speedup"},
                    {"type": "text", "page number": 1, "content": "4.4"},
                ]
            }
        ),
        encoding="utf-8",
    )
    aggressive = postprocess_opendataloader_markdown_outputs(
        output, cleanup_strength="aggressive"
    )
    aggressive_text = (output / "paper_clear.md").read_text(encoding="utf-8")

    assert aggressive.files_created == balanced.files_created == 1
    assert balanced_text == aggressive_text
