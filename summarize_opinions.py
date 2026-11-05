#!/usr/bin/env python3
"""Summarize fetched Sixth Court rulings into one Word document per release date.

Each PDF gets its own Claude request, run with the uploaded
appellate-ruling-summary-json skill, and returns one JSON entry (see
json-contract.md). Entries are saved to opinions/<date>/summaries/<pdf stem>.json,
then brief_docx.py assembles them into opinions/<date>/YYYY-MM-DD-opinions-summary.docx.

A saved entry is never requested again, so rerunning the script is cheap. To redo a
ruling, delete its JSON file and run the script again. API failures are not saved:
the ruling is listed as an error in the document, retried on the next run, and the
script exits with status 1.

Environment:
    ANTHROPIC_API_KEY     required
    CLAUDE_SKILL_ID       required, the uploaded skill's skill_... ID
    CLAUDE_SKILL_VERSION  skver_... ID to pin (default: latest)
    CLAUDE_MODEL          default: claude-sonnet-5-5

Usage:
    python summarize_opinions.py                 # every date folder with unsummarized PDFs
    python summarize_opinions.py --date 10/21/2026
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Callable

import anthropic

from brief_docx import SCHEMA_VERSION, build_document

ROOT = Path(__file__).resolve().parent
OUT_ROOT = ROOT / "opinions"
SYSTEM_PROMPT_FILE = ROOT / "system.txt"
USER_PROMPT_FILE = ROOT / "user.txt"

COURT_NAME = "Texas Sixth Court of Appeals, Texarkana"
DEFAULT_MODEL = "claude-sonnet-5-5"
MAX_TOKENS = 64000
MAX_CONTINUATIONS = 10  # pause_turn resumes allowed for one ruling
TOOLS = [
    {"type": "code_execution_20260521", "name": "code_execution"},
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 4},  # news check only
]
# Reruns a request on another model if the safety classifiers decline it.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def date_to_folder(date_str: str) -> str:
    return datetime.strptime(date_str, "%m/%d/%Y").strftime("%m_%d_%Y")


def folder_date(folder_name: str) -> datetime:
    return datetime.strptime(folder_name, "%m_%d_%Y")


def long_date(value: datetime) -> str:
    return f"{value:%B} {value.day}, {value.year}"


def error_entry(source_file: str, reason: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "error",
        "source_file": source_file,
        "summary": "",
        "reason": reason,
        "review": {"citation_check": "not_run", "news_check": "not_performed", "flags": []},
    }


def entry_problem(entry: object) -> str | None:
    """Return why brief_docx.py can't print this entry, or None if it can."""
    if not isinstance(entry, dict):
        return "the entry is not a JSON object"
    if entry.get("schema_version") != SCHEMA_VERSION:
        return f"schema_version is not {SCHEMA_VERSION}"
    status = entry.get("status")
    if status not in {"summarized", "not_summarized", "error"}:
        return f"unknown status {status!r}"
    if not isinstance(entry.get("review"), dict):
        return "review is missing"
    if status != "summarized":
        return None if str(entry.get("reason") or "").strip() else f"{status} entry has no reason"
    for field in ("case_name", "case_number", "summary"):
        value = entry.get(field)
        if not isinstance(value, str) or not value.strip():
            return f"{field} is missing"
    if entry.get("category") not in {"civil", "criminal"}:
        return "category must be civil or criminal"
    if not isinstance(entry.get("types_of_law"), list):
        return "types_of_law is not a list"
    if not isinstance(entry.get("notations", []), list):
        return "notations is not a list"
    if not isinstance(entry.get("review", {}).get("flags", []), list):
        return "review.flags is not a list"
    if not isinstance(entry.get("news_note"), (dict, type(None))):
        return "news_note is not an object"
    return None


def parse_entry(text: str, stop_reason: str | None, source_file: str) -> dict:
    """Turn the final response into an entry that brief_docx.py can always print."""
    if stop_reason == "refusal":
        return error_entry(source_file, "Claude declined to summarize this ruling; needs a manual summary.")
    if stop_reason != "end_turn":
        return error_entry(source_file, f"The run ended early (stop_reason={stop_reason}).")
    blocks = re.findall(r"```json\s*(\{.*?\})\s*```", text, re.S)
    if not blocks:
        return error_entry(source_file, "The response had no JSON entry.")
    try:
        entry = json.loads(blocks[-1])
    except json.JSONDecodeError as exc:
        return error_entry(source_file, f"The response's JSON could not be parsed ({exc.msg}).")
    problem = entry_problem(entry)
    if problem:
        return error_entry(source_file, f"The response's JSON entry was invalid: {problem}.")
    entry["source_file"] = source_file
    return entry


def summarize_pdf(
    client: anthropic.Anthropic,
    pdf: Path,
    release_date: str,
    model: str,
    skill: dict,
    system_prompt: str,
    user_template: str,
    run_id: str,
) -> dict:
    """Run the skill on one PDF. Anthropic API errors are raised to the caller."""
    with pdf.open("rb") as handle:
        uploaded = client.files.upload(file=(pdf.name, handle, "application/pdf"))
    try:
        user_text = user_template.format(
            pdf_filename=pdf.name, court_name=COURT_NAME, release_date=release_date, run_id=run_id
        )
        messages: list[dict] = [
            {
                "role": "user",
                "content": [
                    {"type": "container_upload", "file_id": uploaded.id},
                    {"type": "text", "text": user_text},
                ],
            }
        ]
        container: dict = {"skills": [skill]}
        for _ in range(MAX_CONTINUATIONS + 1):
            with client.beta.messages.stream(
                model=model,
                max_tokens=MAX_TOKENS,
                betas=[FALLBACK_BETA],
                fallbacks="default",
                system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
                container=container,
                tools=TOOLS,
                messages=messages,
            ) as stream:
                response = stream.get_final_message()
            print(
                f"  {pdf.name}: stop_reason={response.stop_reason} "
                f"input_tokens={response.usage.input_tokens} output_tokens={response.usage.output_tokens}"
            )
            if response.stop_reason != "pause_turn":
                text = "".join(block.text for block in response.content if block.type == "text")
                return parse_entry(text, response.stop_reason, pdf.name)
            # Resume in the same container so files from earlier in the run are kept.
            messages.append({"role": "assistant", "content": response.content})
            container = {"id": response.container.id, "skills": [skill]}
        return error_entry(pdf.name, f"The run was still paused after {MAX_CONTINUATIONS} continuations.")
    finally:
        try:
            client.files.delete(uploaded.id)
        except anthropic.APIError as exc:
            print(f"  warning: could not delete uploaded file {uploaded.id}: {exc}")


def load_saved_entry(path: Path) -> dict | None:
    """Return a usable saved entry, or None so the ruling is summarized again."""
    if not path.exists():
        return None
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return None if entry_problem(entry) else entry


def process_folder(folder: Path, summarize: Callable[[Path, str], dict]) -> int:
    """Summarize unsaved PDFs and rebuild the Word document. Returns the API failure count."""
    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        print(f"Skipping {folder.name}: no PDFs found")
        return 0

    date_value = folder_date(folder.name)
    release_date = long_date(date_value)
    target = folder / f"{date_value:%Y-%m-%d}-opinions-summary.docx"
    summaries = folder / "summaries"

    entries: list[dict] = []
    changed = False
    failures = 0
    for pdf in pdfs:
        saved_path = summaries / f"{pdf.stem}.json"
        entry = load_saved_entry(saved_path)
        if entry is not None:
            entries.append(entry)
            continue

        changed = True
        print(f"Summarizing {folder.name}/{pdf.name} ...")
        try:
            entry = summarize(pdf, release_date)
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
            raise  # Every other ruling would fail the same way.
        except anthropic.APIError as exc:
            failures += 1
            print(f"  ERROR {pdf.name}: {exc}")
            entries.append(error_entry(pdf.name, f"Claude API request failed ({type(exc).__name__}); will retry."))
            continue

        summaries.mkdir(exist_ok=True)
        saved_path.write_text(json.dumps(entry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        entries.append(entry)

    if changed or not target.exists():
        build_document(entries, date=release_date).save(target)
        print(f"Wrote {folder.name}/{target.name}")
    else:
        print(f"Skipping {folder.name}: {target.name} is up to date")
    return failures


def target_folders(date_arg: str | None) -> list[Path]:
    if date_arg:
        folder = OUT_ROOT / date_to_folder(date_arg)
        if not folder.is_dir():
            print(f"No opinion folder for {date_arg}; nothing to summarize.")
            return []
        return [folder]
    return sorted(
        (p for p in OUT_ROOT.iterdir() if p.is_dir() and re.fullmatch(r"\d{2}_\d{2}_\d{4}", p.name)),
        key=lambda p: folder_date(p.name),
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="MM/DD/YYYY; process one date folder only")
    args = ap.parse_args()

    if not OUT_ROOT.exists():
        raise SystemExit(f"No opinions directory at {OUT_ROOT}")
    skill_id = os.environ.get("CLAUDE_SKILL_ID")
    if not skill_id:
        raise SystemExit("CLAUDE_SKILL_ID is required.")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY is required.")

    client = anthropic.Anthropic()
    model = os.environ.get("CLAUDE_MODEL") or DEFAULT_MODEL
    skill = {
        "type": "custom",
        "skill_id": skill_id,
        "version": os.environ.get("CLAUDE_SKILL_VERSION") or "latest",
    }
    system_prompt = SYSTEM_PROMPT_FILE.read_text(encoding="utf-8")
    user_template = USER_PROMPT_FILE.read_text(encoding="utf-8")
    run_id = os.environ.get("GITHUB_RUN_ID", "local")

    def summarize(pdf: Path, release_date: str) -> dict:
        return summarize_pdf(client, pdf, release_date, model, skill, system_prompt, user_template, run_id)

    failures = 0
    try:
        for folder in target_folders(args.date):
            failures += process_folder(folder, summarize)
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
        raise SystemExit(f"Claude API rejected the credentials: {exc}") from exc

    if failures:
        print(f"{failures} ruling(s) failed and will be retried on the next run.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
