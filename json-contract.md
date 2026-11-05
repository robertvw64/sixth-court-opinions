# JSON contract (schema 1.0)

One skill run returns one JSON object. The workflow saves it (one file per ruling), then a Python script loads a day's objects and passes each to `add_entry(doc, entry)` in `scripts/brief_docx.py`, or passes the whole list to `build_document(entries, date)`.

## Fields

| Field | Type | Required when | Notes |
|---|---|---|---|
| `schema_version` | string | always | `"1.0"` |
| `status` | string | always | `summarized`, `not_summarized`, or `error` |
| `source_file` | string | always | PDF file name |
| `case_name` | string | summarized | Daily Brief party listing |
| `case_number` | string | summarized | As printed; first number if consolidated |
| `case_numbers` | list of strings | summarized | All numbers on the opinion; includes `case_number` |
| `category` | string | summarized | `civil` or `criminal` |
| `court` | string | summarized | `Texas Court of Appeals` for Texas intermediate courts |
| `subcourt` | string | summarized | `Sixth`, or `""` |
| `judge` | string | summarized | Full names, author first, `"; "`-separated; or `Per curiam` |
| `date_decided` | string or null | summarized | e.g. `October 21, 2026` |
| `ruling_type` | string | summarized | `merits`, `dismissal`, `mandamus_granted`, `mandamus_denied`, `habeas_granted`, `habeas_denied`, `modified_affirmed`, `anders`, `procedural`, `other` |
| `disposition` | string or null | summarized | `Affirmed`, `Affirmed in part`, `Reversed`, `Reversed in part`, `Vacated`, `Vacated in part`, or null; matches the summary's ending |
| `types_of_law` | list of strings | summarized | New category names from the matching list in `categories.md` |
| `summary` | string | summarized | Summary with ` {{p. X, l. Y}}` review citations; `""` otherwise |
| `summary_clean` | string | summarized | Summary without citations; written by `validate_entry.py --write` |
| `news_note` | object or null | optional | `{"reason": str, "url": str or null}` |
| `pitch` | string | summarized | `Yes — reason` or `No — reason` |
| `notations` | list of strings | summarized | Subset of, in order: `Below minimum page count`, `Do not publish` |
| `page_count` | integer | summarized | PDF pages |
| `reason` | string or null | not_summarized, error | One line; null for summarized |
| `review` | object | always | `citation_check`: `passed`/`failed`/`not_run`; `news_check`: `performed`/`not_performed`; `flags`: list of strings for the editor |

The assembler prints, in this order: case name, Case number, Court, Subcourt, Judge, Types of law, summary, "Well-known/news coverage:" note, Pitch, notations, then reviewer flags (small orange text, can be turned off). Not-summarized and error entries go in a "Not summarized" list at the end.

## Example: summarized

```json
{
  "schema_version": "1.0",
  "status": "summarized",
  "source_file": "06-26-00083-CV.pdf",
  "case_name": "Adept Machine Tools v. Underwood",
  "case_number": "06-26-00083-CV",
  "case_numbers": [
    "06-26-00083-CV"
  ],
  "category": "civil",
  "court": "Texas Court of Appeals",
  "subcourt": "Sixth",
  "judge": "Charles van Cleef; Scott E. Stevens; Jeff Rambin",
  "date_decided": "October 21, 2026",
  "ruling_type": "merits",
  "disposition": "Affirmed",
  "types_of_law": [
    "Civil Procedure",
    "Tort",
    "Commercial"
  ],
  "summary": "In an opinion written by J. Charles van Cleef, the Texas Sixth Court of Appeals rules that the trial court properly exercised jurisdiction over a North Carolina machine tool company in a lawsuit brought by the widow and parents of a lathe operator {{p. 1, l. 13; p. 2, ll. 5-12; p. 2, l. 21; p. 6, ll. 19-20}}, who died when the machine ejected a spinning object that beat its metal door open with such force that he was thrown back several feet {{p. 2, ll. 2-5}}. The family alleges the company installed the chuck, a part meant to hold metal sprockets in place during machining, that released a steel sprocket inside the machine, and then shipped the machine to his employer in Texas {{p. 5, ll. 2-4; p. 5, ll. 15-21}}. The company argued it had no presence in Texas and merely arranged the shipment {{p. 6, ll. 25-27; p. 7, ll. 1-5}}, but it billed a Texas company for 18 hours of work that included modifying the machine while knowing it was headed to a Texas customer, so it could reasonably anticipate being sued in Texas {{p. 7, ll. 15-19; p. 14, ll. 14-18; p. 15, ll. 2-4}}. Affirmed {{p. 18, l. 2}}. J. Scott Stevens and J. Jeff Rambin concur {{p. 1, l. 12}}.",
  "summary_clean": "(filled in by validate_entry.py --write)",
  "news_note": null,
  "pitch": "Yes — a lathe ejected a spinning object that beat its metal door open and threw the operator back several feet, killing him.",
  "notations": [],
  "page_count": 18,
  "reason": null,
  "review": {
    "citation_check": "passed",
    "news_check": "performed",
    "flags": []
  }
}
```

## Example: not_summarized (hypothetical)

```json
{
  "schema_version": "1.0",
  "status": "not_summarized",
  "source_file": "06-26-00191-CV.pdf",
  "case_name": "Doe v. Roe",
  "case_number": "06-26-00191-CV",
  "case_numbers": [
    "06-26-00191-CV"
  ],
  "category": "civil",
  "ruling_type": "procedural",
  "summary": "",
  "reason": "Order granting an extension of time to file a brief; decides nothing.",
  "review": {
    "citation_check": "not_run",
    "news_check": "not_performed",
    "flags": []
  }
}
```

## Example: error (hypothetical)

```json
{
  "schema_version": "1.0",
  "status": "error",
  "source_file": "06-26-00200-CR.pdf",
  "summary": "",
  "reason": "PDF has no extractable text (scanned image); needs OCR or manual summary.",
  "review": {
    "citation_check": "not_run",
    "news_check": "not_performed",
    "flags": []
  }
}
```

## Using the entries in Python

```python
import json, pathlib
from brief_docx import build_document

entries = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(pathlib.Path("summaries").glob("*.json"))]
build_document(entries, date="October 21, 2026").save("Daily Brief Summaries for October 21, 2026.docx")
build_document(entries, date="October 21, 2026", keep_citations=False, show_flags=False).save("clean.docx")
```
