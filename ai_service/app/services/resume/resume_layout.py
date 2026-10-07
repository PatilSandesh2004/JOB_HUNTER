"""Read the look of the candidate's own resume (fonts, sizes, section names/order, margins, header alignment).

The tailored resume is rendered with this layout so it looks like the resume the user uploaded, not a
generic template. Sections the profile model cannot represent (Projects, Certifications, ...) are
carried over verbatim from the original so tailoring never drops content.
"""

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("jobpilot.resume_layout")

_KNOWN = {
    "summary": {"summary", "professional summary", "profile", "professional profile", "objective",
                "career objective", "about me", "about", "executive summary"},
    "skills": {"skills", "technical skills", "key skills", "core competencies", "core skills",
               "skills & tools", "skills and tools", "technologies", "tech stack"},
    "experience": {"experience", "work experience", "professional experience", "employment history",
                   "work history", "employment", "career history", "internships", "internship experience"},
    "education": {"education", "academic background", "education & training", "academics",
                  "academic qualifications", "qualifications"},
}
_EXTRA = {"projects", "personal projects", "academic projects", "certifications", "certificates",
          "achievements", "awards", "honors", "publications", "languages", "interests", "hobbies",
          "volunteering", "volunteer experience", "extracurricular activities", "courses", "training",
          "additional information", "references", "positions of responsibility"}
_SERIF = re.compile(r"times|georgia|garamond|cambria|serif|palatino|book|minion|century|charter", re.I)
_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")
_STYLE_SUFFIX = re.compile(r"[-,](bold|italic|oblique|regular|bolditalic|light|medium|semibold|mt|ps|psmt)+.*$", re.I)


@dataclass
class ResumeLayout:
    font_stack: str = "Arial, Helvetica, sans-serif"
    body_pt: float = 10.5
    name_pt: float = 20.0
    heading_pt: float = 11.0
    heading_color: str = "#111111"
    heading_upper: bool = True
    heading_rule: bool = True
    centered_header: bool = False
    margin_mm: tuple[float, float] = (14.0, 15.0)  # (top/bottom, left/right)
    labels: dict[str, str] = field(default_factory=dict)  # canonical key -> heading text as written
    order: list[str] = field(default_factory=list)  # canonical keys in original order
    extras: list[tuple[str, list[str]]] = field(default_factory=list)  # (heading, verbatim lines)

    def label(self, key: str, default: str) -> str:
        return self.labels.get(key, default)


def _canonical(text: str) -> str | None:
    norm = re.sub(r"[^a-z& ]", "", text.lower()).strip()
    for key, names in _KNOWN.items():
        if norm in names:
            return key
    return "extra" if norm in _EXTRA else None


def _family(fontname: str | None) -> str | None:
    if not fontname:
        return None
    base = _STYLE_SUFFIX.sub("", _SUBSET_PREFIX.sub("", fontname))
    base = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", base).replace("-", " ").strip()
    if not base:
        return None
    generic = "serif" if _SERIF.search(base) else "sans-serif"
    return f'"{base}", {generic}'


def _hex(color) -> str | None:
    try:
        if isinstance(color, (int, float)):
            color = (color,)
        vals = [float(c) for c in color]
    except (TypeError, ValueError):
        return None
    if len(vals) == 1:
        vals = vals * 3
    if len(vals) != 3 or any(v < 0 or v > 1 for v in vals):
        return None
    return "#" + "".join(f"{round(v * 255):02x}" for v in vals)


def analyze_resume_layout(path: str | Path | None) -> ResumeLayout | None:
    """Best-effort layout of an uploaded PDF/DOCX; None when it cannot be read."""
    if not path:
        return None
    p = Path(path)
    try:
        if p.suffix.lower() == ".pdf":
            return _from_pdf(p)
        if p.suffix.lower() == ".docx":
            return _from_docx(p)
    except Exception as exc:
        logger.warning("Could not read resume layout from %s: %s", p.name, exc)
    return None


def _finish(layout: ResumeLayout, sections: list[tuple[str, str, list[str]]]) -> ResumeLayout:
    """sections: (canonical key or 'extra', heading text, lines)."""
    for key, label, lines in sections:
        if key == "extra":
            layout.order.append(f"extra:{len(layout.extras)}")
            layout.extras.append((label, [ln for ln in lines if ln.strip()]))
        elif key not in layout.labels:
            layout.labels[key] = label
            layout.order.append(key)
    if sections:
        headings = [s[1] for s in sections]
        layout.heading_upper = sum(h.isupper() for h in headings) >= len(headings) / 2
    return layout


def _from_pdf(path: Path) -> ResumeLayout | None:
    import pdfplumber

    layout = ResumeLayout()
    sections: list[tuple[str, str, list[str]]] = []
    with pdfplumber.open(path) as pdf:
        if not pdf.pages:
            return None
        page = pdf.pages[0]
        words = page.extract_words(extra_attrs=["fontname", "size", "non_stroking_color"], keep_blank_chars=False)
        if not words:
            return None
        sizes: Counter[float] = Counter()
        fonts: Counter[str] = Counter()
        for w in words:
            sizes[round(w["size"], 1)] += len(w["text"])
            fam = _family(w["fontname"])
            if fam:
                fonts[fam] += len(w["text"])
        layout.body_pt = sizes.most_common(1)[0][0]
        if fonts:
            layout.font_stack = fonts.most_common(1)[0][0]
        layout.margin_mm = (
            min(max(min(w["top"] for w in words) / 72 * 25.4, 8.0), 25.0),
            min(max(min(w["x0"] for w in words) / 72 * 25.4, 8.0), 25.0),
        )

        lines: list[dict] = []
        for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
            if lines and abs(lines[-1]["top"] - w["top"]) < 3:
                lines[-1]["words"].append(w)
            else:
                lines.append({"top": w["top"], "words": [w]})
        for ln in lines:
            ln["text"] = " ".join(w["text"] for w in ln["words"])
            ln["size"] = max(w["size"] for w in ln["words"])
            ln["x0"], ln["x1"] = ln["words"][0]["x0"], ln["words"][-1]["x1"]

        first = lines[0]
        layout.name_pt = round(first["size"], 1)
        layout.centered_header = abs((first["x0"] + first["x1"]) / 2 - page.width / 2) < page.width * 0.06

        current: tuple[str, str, list[str]] | None = None
        for ln in lines[1:]:
            key = _canonical(ln["text"]) if len(ln["text"]) <= 40 else None
            if key:
                if current:
                    sections.append(current)
                current = (key, ln["text"].strip(), [])
                layout.heading_pt = round(ln["size"], 1)
                color = _hex(ln["words"][0].get("non_stroking_color"))
                if color:
                    layout.heading_color = color
            elif current:
                current[2].append(ln["text"])
        if current:
            sections.append(current)

        rules = [
            r for r in [*page.lines, *page.rects]
            if (r["x1"] - r["x0"]) > page.width * 0.4 and (r["bottom"] - r["top"]) < 2.5
        ]
        layout.heading_rule = bool(rules)
    return _finish(layout, sections)


def _from_docx(path: Path) -> ResumeLayout | None:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = Document(str(path))
    layout = ResumeLayout()
    normal = doc.styles["Normal"].font
    if normal.name:
        layout.font_stack = f'"{normal.name}", {"serif" if _SERIF.search(normal.name) else "sans-serif"}'
    if normal.size:
        layout.body_pt = round(normal.size.pt, 1)
    if doc.sections:
        s = doc.sections[0]
        if s.left_margin and s.top_margin:
            layout.margin_mm = (
                min(max(s.top_margin.mm, 8.0), 25.0),
                min(max(s.left_margin.mm, 8.0), 25.0),
            )
    paras = [p for p in doc.paragraphs if p.text.strip()]
    if not paras:
        return None
    first = paras[0]
    layout.centered_header = first.alignment == WD_ALIGN_PARAGRAPH.CENTER
    sizes = [r.font.size.pt for r in first.runs if r.font.size]
    if sizes:
        layout.name_pt = round(max(sizes), 1)
    sections: list[tuple[str, str, list[str]]] = []
    current: tuple[str, str, list[str]] | None = None
    for p in paras[1:]:
        text = p.text.strip()
        key = _canonical(text) if len(text) <= 40 else None
        if key:
            if current:
                sections.append(current)
            current = (key, text, [])
            run_sizes = [r.font.size.pt for r in p.runs if r.font.size]
            if run_sizes:
                layout.heading_pt = round(max(run_sizes), 1)
        elif current:
            current[2].append(text)
    if current:
        sections.append(current)
    return _finish(layout, sections)
