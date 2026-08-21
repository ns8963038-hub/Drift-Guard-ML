"""Generate the plain, presentation-friendly deck.

The first deck reads well and presents badly: bullets averaging 16 words, the
longest 38. Bullets that long are complete sentences, so a presenter has no
choice but to read them out, and the audience reads ahead instead of listening.

This version inverts that. The slide carries a short cue and the sentence the
presenter actually says lives in the speaker notes, where the audience never
sees it.

Words and figures come from deck_content, shared with the styled deck, so a
change to one cannot leave the other stating something different. Layout
helpers are shared with build_ppt.py for the same reason.

    python scripts/build_ppt_simple.py   # -> dist/DriftGuard_Presentation_Simple.pptx
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pptx import Presentation  # noqa: E402
from pptx.enum.text import PP_ALIGN  # noqa: E402
from pptx.util import Inches, Pt  # noqa: E402

import deck_content as C  # noqa: E402
from build_ppt import (  # noqa: E402
    BODY_W,
    GREY,
    MARGIN,
    RULE,
    SLIDE_H,
    SLIDE_W,
    _blank,
    _text,
    heading,
    table,
)

OUT = (
    Path(__file__).resolve().parent.parent
    / "dist"
    / "DriftGuard_Presentation_Simple.pptx"
)


def cues(slide, items, top=Inches(2.0), size=22):
    """Short bullets, generously spaced. No cue should reach two lines."""
    box = slide.shapes.add_textbox(MARGIN, top, BODY_W, SLIDE_H - top - Inches(0.5))
    frame = box.text_frame
    frame.word_wrap = True

    for i, item in enumerate(items):
        para = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        para.space_after = Pt(16)
        para.line_spacing = 1.1
        run = para.add_run()
        run.text = f"•   {item}"
        run.font.size = Pt(size)
        run.font.name = "Calibri"


def notes(slide, text):
    """What the presenter says. Never shown to the audience."""
    slide.notes_slide.notes_text_frame.text = text.strip()


def build():
    prs = Presentation()
    prs.slide_width, prs.slide_height = SLIDE_W, SLIDE_H

    # ── Title ────────────────────────────────────────────────────────
    s = _blank(prs)
    _, run = _text(
        s,
        MARGIN,
        Inches(2.4),
        BODY_W,
        Inches(1.2),
        44,
        bold=True,
        align=PP_ALIGN.CENTER,
    )
    run.text = C.TITLE["name"]
    _, run = _text(
        s, MARGIN, Inches(3.35), BODY_W, Inches(1.0), 22, align=PP_ALIGN.CENTER
    )
    run.text = C.TITLE["subtitle"]
    line = s.shapes.add_shape(1, Inches(5.4), Inches(4.6), Inches(2.5), Pt(1.2))
    line.fill.solid()
    line.fill.fore_color.rgb = RULE
    line.line.fill.background()
    line.shadow.inherit = False
    _, run = _text(
        s,
        MARGIN,
        Inches(5.0),
        BODY_W,
        Inches(1.2),
        15,
        color=GREY,
        align=PP_ALIGN.CENTER,
    )
    run.text = C.TITLE["footer"]
    notes(s, C.TITLE["notes"])

    # ── Sections 1-16 ────────────────────────────────────────────────
    for spec in C.SLIDES:
        s = _blank(prs)
        heading(s, spec["number"], spec["title"])

        below = Inches(2.0)
        if "table" in spec:
            t = spec["table"]
            table(
                s,
                t["headers"],
                t["rows"],
                top=Inches(1.95),
                col_widths=t["widths"],
                size=t.get("size", 14),
            )
            below = Inches(1.95 + (len(t["rows"]) + 1) * 0.42 + 0.35)
        if "cues" in spec:
            size = 20 if len(spec["cues"]) > 5 or "table" in spec else 22
            cues(s, spec["cues"], top=below, size=size)

        notes(s, spec["notes"])

    # ── 17. References ───────────────────────────────────────────────
    s = _blank(prs)
    heading(s, "17", "References")
    box = s.shapes.add_textbox(MARGIN, Inches(1.9), BODY_W, Inches(5.2))
    frame = box.text_frame
    frame.word_wrap = True
    for i, ref in enumerate(C.REFERENCES):
        para = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        para.space_after = Pt(9)
        run = para.add_run()
        run.text = f"{i + 1}.   {ref}"
        run.font.size = Pt(13)
        run.font.name = "Calibri"
    notes(s, C.REFERENCES_NOTES)

    OUT.parent.mkdir(exist_ok=True)
    prs.save(OUT)
    return prs


if __name__ == "__main__":
    build()
    print(f"Wrote {OUT.name}")
