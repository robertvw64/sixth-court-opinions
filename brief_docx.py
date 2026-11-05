#!/usr/bin/env python3
r"""Assemble Daily Brief JSON entries (schema 1.0) into a Word document with python-docx.

Use as a library from the workflow's Python script:

    from docx import Document
    from brief_docx import ensure_styles, add_heading_block, add_entry, add_not_summarized, build_document

    # One call does everything (sorts civil then criminal, by case number):
    doc = build_document(entries, date="October 21, 2026")
    doc.save("Daily Brief Summaries for October 21, 2026.docx")

    # Or drive it yourself, one entry at a time, into your own Document():
    doc = Document()
    ensure_styles(doc)
    add_heading_block(doc, date="October 21, 2026", court="Texas Court of Appeals", subcourt="Sixth")
    for entry in entries:                      # each entry = one skill run's JSON (a dict)
        if entry["status"] == "summarized":
            add_entry(doc, entry)              # keep_citations=False for a clean copy
    add_not_summarized(doc, [e for e in entries if e["status"] != "summarized"])

Or from the command line:

    python brief_docx.py out.docx --date "October 21, 2026" summaries/*.json [--no-citations]

Review citations (" {{p. 2, ll. 4-8}}") are printed in a character style named
"Review Citation" (small, gray, highlighted). Editors remove them all in Word with
Find & Replace, wildcards on: find " \{\{*\}\}", replace with nothing.
"""
import argparse
import json
import re
import sys

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_COLOR_INDEX
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

SCHEMA_VERSION = "1.0"
CITE = re.compile(r"(\s*\{\{.*?\}\})")
CITATION_STYLE = "Review Citation"


def ensure_styles(doc):
    """Add the 'Review Citation' character style if the document doesn't have it yet."""
    names = {s.name for s in doc.styles}
    if CITATION_STYLE not in names:
        st = doc.styles.add_style(CITATION_STYLE, WD_STYLE_TYPE.CHARACTER)
        st.font.size = Pt(8)
        st.font.color.rgb = RGBColor(0x59, 0x59, 0x59)
        st.font.highlight_color = WD_COLOR_INDEX.GRAY_25
    return doc


def _add_cited_text(par, text, keep_citations):
    for part in CITE.split(text):
        if not part:
            continue
        if CITE.fullmatch(part):
            if keep_citations:
                par.add_run(part, style=CITATION_STYLE)
        else:
            par.add_run(part)


def _add_hyperlink(par, url, text=None):
    r_id = par.part.relate_to(url, RT.HYPERLINK, is_external=True)
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), r_id)
    run = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "0563C1")
    u = OxmlElement("w:u")
    u.set(qn("w:val"), "single")
    rpr.append(color)
    rpr.append(u)
    run.append(rpr)
    t = OxmlElement("w:t")
    t.text = text or url
    t.set(qn("xml:space"), "preserve")
    run.append(t)
    link.append(run)
    par._p.append(link)


def _add_field(doc, label, value):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(0)
    r = p.add_run(f"{label}: ")
    r.bold = True
    p.add_run(value or "")


def add_heading_block(doc, date=None, court=None, subcourt=None):
    """Document title plus an italic court line."""
    doc.add_heading(f"Daily Brief Summaries{' for ' + date if date else ''}", level=1)
    if court:
        p = doc.add_paragraph()
        p.add_run(f"{court}{' — ' + subcourt if subcourt else ''}").italic = True


def add_entry(doc, entry, keep_citations=True, show_flags=True):
    """Append one summarized ruling to `doc` in Daily Brief order:
    case name, fields, summary, Well-known/news coverage note, Pitch, notations, reviewer flags.
    """
    if entry.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"{entry.get('source_file')}: expected schema_version {SCHEMA_VERSION}")
    if entry.get("status") != "summarized":
        raise ValueError(f"{entry.get('source_file')}: add_entry only takes summarized entries; "
                         "pass the others to add_not_summarized")
    ensure_styles(doc)

    h = doc.add_paragraph()
    h.paragraph_format.space_before = Pt(10)
    h.paragraph_format.space_after = Pt(2)
    r = h.add_run(entry["case_name"])
    r.bold = True
    r.font.size = Pt(12)

    _add_field(doc, "Case number", entry["case_number"])
    _add_field(doc, "Court", entry.get("court"))
    _add_field(doc, "Subcourt", entry.get("subcourt"))
    _add_field(doc, "Judge", entry.get("judge"))
    _add_field(doc, "Types of law", "; ".join(entry.get("types_of_law") or []))

    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(4)
    _add_cited_text(p, entry["summary"], keep_citations)

    note = entry.get("news_note")
    if note:
        q = doc.add_paragraph()
        q.paragraph_format.space_after = Pt(2)
        q.add_run("Well-known/news coverage: ").bold = True
        q.add_run(note.get("reason", "").strip())
        if note.get("url"):
            q.add_run(" ")
            _add_hyperlink(q, note["url"])

    if entry.get("pitch"):
        q = doc.add_paragraph()
        rr = q.add_run(f"Pitch: {entry['pitch']}")
        rr.italic = True
        rr.font.color.rgb = RGBColor(0x55, 0x55, 0x55)

    for n in entry.get("notations") or []:      # "Below minimum page count", then "Do not publish"
        q = doc.add_paragraph()
        q.paragraph_format.space_after = Pt(0)
        q.add_run(n).bold = True

    flags = (entry.get("review") or {}).get("flags") or []
    if show_flags and flags:
        q = doc.add_paragraph()
        rr = q.add_run("Reviewer flags: " + " | ".join(flags))
        rr.font.size = Pt(9)
        rr.font.color.rgb = RGBColor(0xA0, 0x40, 0x00)


def add_not_summarized(doc, entries):
    """List not_summarized and error entries at the end so nothing is skipped silently."""
    if not entries:
        return
    doc.add_heading("Not summarized", level=2)
    for e in entries:
        label = e.get("case_number") or e.get("source_file", "")
        tag = " (error)" if e.get("status") == "error" else ""
        doc.add_paragraph(f"{label}{tag} — {e.get('reason', '')}", style="List Bullet")


def build_document(entries, date=None, keep_citations=True, show_flags=True):
    """Build a complete Document: civil entries first, then criminal, each in case-number order."""
    doc = Document()
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = Pt(11)
    ensure_styles(doc)
    done = [e for e in entries if e.get("status") == "summarized"]
    rest = [e for e in entries if e.get("status") != "summarized"]
    court = done[0].get("court") if done else None
    subcourt = done[0].get("subcourt") if done else None
    add_heading_block(doc, date, court, subcourt)
    for title, cat in (("Civil", "civil"), ("Criminal", "criminal")):
        group = sorted((e for e in done if e.get("category") == cat), key=lambda e: e["case_number"])
        if group:
            doc.add_heading(title, level=2)
            for e in group:
                add_entry(doc, e, keep_citations, show_flags)
    add_not_summarized(doc, rest)
    return doc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("output")
    ap.add_argument("entries", nargs="+", help="JSON files, one entry each")
    ap.add_argument("--date", default=None)
    ap.add_argument("--no-citations", action="store_true")
    ap.add_argument("--no-flags", action="store_true")
    a = ap.parse_args()
    entries = []
    for path in a.entries:
        with open(path, encoding="utf-8") as fh:
            entries.append(json.load(fh))
    build_document(entries, a.date, not a.no_citations, not a.no_flags).save(a.output)
    print(f"Wrote {a.output} ({sum(e.get('status') == 'summarized' for e in entries)} summaries)")


if __name__ == "__main__":
    sys.exit(main())
