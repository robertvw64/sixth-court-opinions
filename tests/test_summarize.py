"""Offline tests for summarize_opinions.py. Run with: python -m pytest tests/test_summarize.py"""
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from docx import Document

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import summarize_opinions as s  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = (ROOT / "json-contract.md").read_text(encoding="utf-8")
EXAMPLES = [json.loads(b) for b in re.findall(r"```json\n(\{.*?\})\n```", CONTRACT, re.S)]
SUMMARIZED, NOT_SUMMARIZED, ERROR = EXAMPLES


def fenced(entry):
    return f"Done.\n\n```json\n{json.dumps(entry)}\n```"


def api_error():
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.InternalServerError(
        "boom", response=httpx2.Response(500, request=request), body=None
    )


def auth_error():
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.AuthenticationError(
        "bad key", response=httpx2.Response(401, request=request), body=None
    )


def make_folder(tmp_path, *names):
    folder = tmp_path / "10_21_2026"
    folder.mkdir()
    for name in names:
        (folder / name).write_bytes(b"%PDF-1.4")
    return folder


def doc_text(path):
    return "\n".join(p.text for p in Document(path).paragraphs)


# --- parse_entry ---

def test_contract_examples_all_parse():
    assert len(EXAMPLES) == 3
    for example in EXAMPLES:
        assert s.parse_entry(fenced(example), "end_turn", example["source_file"])["status"] == example["status"]


def test_parse_uses_last_block_and_real_file_name():
    other = dict(SUMMARIZED, case_name="Earlier draft")
    text = fenced(other) + "\n" + fenced(SUMMARIZED)
    entry = s.parse_entry(text, "end_turn", "actual name.pdf")
    assert entry["case_name"] == SUMMARIZED["case_name"]
    assert entry["source_file"] == "actual name.pdf"


@pytest.mark.parametrize(
    "text, stop_reason, expected",
    [
        (fenced(SUMMARIZED), "refusal", "declined"),
        ("partial", "max_tokens", "stop_reason=max_tokens"),
        ("no block here", "end_turn", "no JSON entry"),
        ("```json\n{not json}\n```", "end_turn", "could not be parsed"),
    ],
)
def test_parse_failures_become_error_entries(text, stop_reason, expected):
    entry = s.parse_entry(text, stop_reason, "x.pdf")
    assert entry["status"] == "error"
    assert expected in entry["reason"]
    assert s.entry_problem(entry) is None


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": "2.0"},
        {"status": "done"},
        {"case_number": ""},
        {"category": "family"},
        {"types_of_law": "Tort"},
        {"news_note": "yes"},
        {"review": None},
    ],
)
def test_entries_the_assembler_cannot_print_are_rejected(change):
    entry = s.parse_entry(fenced({**SUMMARIZED, **change}), "end_turn", "x.pdf")
    assert entry["status"] == "error"
    assert "invalid" in entry["reason"]


# --- summarize_pdf request shape ---

class FakeStream:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.response


def response(stop_reason, text="", container_id="cntr_1"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=text)],
        container=SimpleNamespace(id=container_id),
        usage=SimpleNamespace(input_tokens=1, output_tokens=2),
    )


class FakeClient:
    def __init__(self, responses, delete_error=None):
        self.responses = iter(responses)
        self.requests = []
        self.uploads = []
        self.deleted = []
        self.delete_error = delete_error
        self.files = SimpleNamespace(upload=self._upload, delete=self._delete)
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _upload(self, file):
        self.uploads.append(file[0::2])
        return SimpleNamespace(id="file_1")

    def _delete(self, file_id):
        self.deleted.append(file_id)
        if self.delete_error:
            raise self.delete_error

    def _stream(self, **kwargs):
        # Copy the list: the code under test appends to it after this call.
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        item = next(self.responses)
        if isinstance(item, Exception):
            raise item
        return FakeStream(item)


SKILL = {"type": "custom", "skill_id": "skill_x", "version": "skver_x"}


def run(client, tmp_path):
    pdf = tmp_path / "06-26-00083-CV (2).pdf"
    pdf.write_bytes(b"%PDF-1.4")
    template = (ROOT / "user.txt").read_text(encoding="utf-8")
    return s.summarize_pdf(client, pdf, "October 21, 2026", "claude-sonnet-5-5", SKILL, "SYS", template, "42")


def test_request_uses_skill_upload_and_prompts(tmp_path):
    client = FakeClient([response("end_turn", fenced(SUMMARIZED))])
    entry = run(client, tmp_path)
    assert entry["status"] == "summarized"
    assert entry["source_file"] == "06-26-00083-CV (2).pdf"

    request = client.requests[0]
    assert request["container"] == {"skills": [SKILL]}
    assert request["model"] == "claude-sonnet-5-5"
    assert request["fallbacks"] == "default"
    assert request["betas"] == ["server-side-fallback-2026-07-01"]
    assert {t["type"] for t in request["tools"]} == {"code_execution_20260521", "web_search_20260209"}
    assert request["system"][0]["text"] == "SYS"
    assert "metadata" not in request

    upload, prompt = request["messages"][0]["content"]
    assert upload == {"type": "container_upload", "file_id": "file_1"}
    assert "- File: 06-26-00083-CV (2).pdf" in prompt["text"]
    assert "Texas Sixth Court of Appeals, Texarkana" in prompt["text"]
    assert "October 21, 2026" in prompt["text"]
    assert "42" in prompt["text"]
    assert client.uploads == [("06-26-00083-CV (2).pdf", "application/pdf")]
    assert client.deleted == ["file_1"]


def test_pause_turn_resumes_in_same_container(tmp_path):
    paused = response("pause_turn", "working", "cntr_9")
    client = FakeClient([paused, response("end_turn", fenced(SUMMARIZED))])
    assert run(client, tmp_path)["status"] == "summarized"
    assert client.requests[1]["container"] == {"id": "cntr_9", "skills": [SKILL]}
    assert client.requests[1]["messages"][1] == {"role": "assistant", "content": paused.content}


def test_endless_pause_gives_error_entry(tmp_path):
    client = FakeClient([response("pause_turn")] * (s.MAX_CONTINUATIONS + 1))
    assert "still paused" in run(client, tmp_path)["reason"]
    assert client.deleted == ["file_1"]


def test_upload_is_deleted_when_request_fails(tmp_path):
    client = FakeClient([api_error()])
    with pytest.raises(anthropic.InternalServerError):
        run(client, tmp_path)
    assert client.deleted == ["file_1"]


def test_failed_delete_does_not_lose_the_summary(tmp_path):
    client = FakeClient([response("end_turn", fenced(SUMMARIZED))], delete_error=api_error())
    assert run(client, tmp_path)["status"] == "summarized"


# --- process_folder ---

def test_folder_writes_docx_and_entries_in_date_folder(tmp_path):
    folder = make_folder(tmp_path, "06-26-00083-CV.pdf", "06-26-00191-CV.pdf", "06-26-00200-CR.pdf")
    by_name = {e["source_file"]: e for e in EXAMPLES}
    dates = set()

    def summarize(pdf, release_date):
        dates.add(release_date)
        return by_name[pdf.name]

    assert s.process_folder(folder, summarize) == 0
    assert dates == {"October 21, 2026"}
    assert sorted(p.name for p in (folder / "summaries").iterdir()) == [
        "06-26-00083-CV.json", "06-26-00191-CV.json", "06-26-00200-CR.json",
    ]
    text = doc_text(folder / "2026-10-21-opinions-summary.docx")
    assert "Daily Brief Summaries for October 21, 2026" in text
    assert "Adept Machine Tools v. Underwood" in text
    assert "{{p. 1, l. 13" in text
    assert "Pitch: Yes" in text
    assert "Not summarized" in text
    assert "06-26-00191-CV" in text and "06-26-00200-CR.pdf (error)" in text


def test_rerun_makes_no_requests_and_keeps_docx(tmp_path):
    folder = make_folder(tmp_path, "06-26-00083-CV.pdf")
    s.process_folder(folder, lambda pdf, d: SUMMARIZED)
    target = folder / "2026-10-21-opinions-summary.docx"
    before = target.stat().st_mtime_ns

    def fail(pdf, d):
        raise AssertionError("should not call Claude")

    assert s.process_folder(folder, fail) == 0
    assert target.stat().st_mtime_ns == before


def test_missing_docx_is_rebuilt_from_saved_entries(tmp_path):
    folder = make_folder(tmp_path, "06-26-00083-CV.pdf")
    s.process_folder(folder, lambda pdf, d: SUMMARIZED)
    target = folder / "2026-10-21-opinions-summary.docx"
    target.unlink()

    def fail(pdf, d):
        raise AssertionError("should not call Claude")

    s.process_folder(folder, fail)
    assert target.exists()


def test_api_failure_is_listed_not_saved_and_retried(tmp_path):
    folder = make_folder(tmp_path, "06-26-00083-CV.pdf")

    def fail(pdf, d):
        raise api_error()

    assert s.process_folder(folder, fail) == 1
    assert not (folder / "summaries" / "06-26-00083-CV.json").exists()
    target = folder / "2026-10-21-opinions-summary.docx"
    assert "will retry" in doc_text(target)

    assert s.process_folder(folder, lambda pdf, d: SUMMARIZED) == 0
    text = doc_text(target)
    assert "will retry" not in text
    assert "Adept Machine Tools" in text


def test_one_failure_keeps_other_rulings(tmp_path):
    folder = make_folder(tmp_path, "06-26-00083-CV.pdf", "06-26-00084-CV.pdf")

    def summarize(pdf, d):
        if pdf.name.startswith("06-26-00084"):
            raise api_error()
        return SUMMARIZED

    assert s.process_folder(folder, summarize) == 1
    assert (folder / "summaries" / "06-26-00083-CV.json").exists()


def test_bad_credentials_stop_the_run(tmp_path):
    folder = make_folder(tmp_path, "06-26-00083-CV.pdf")

    def fail(pdf, d):
        raise auth_error()

    with pytest.raises(anthropic.AuthenticationError):
        s.process_folder(folder, fail)


def test_corrupt_saved_entry_is_summarized_again(tmp_path):
    folder = make_folder(tmp_path, "06-26-00083-CV.pdf")
    (folder / "summaries").mkdir()
    (folder / "summaries" / "06-26-00083-CV.json").write_text("{broken", encoding="utf-8")
    assert s.process_folder(folder, lambda pdf, d: SUMMARIZED) == 0
    assert json.loads((folder / "summaries" / "06-26-00083-CV.json").read_text(encoding="utf-8"))["status"] == "summarized"


def test_folder_without_pdfs_is_skipped(tmp_path):
    folder = make_folder(tmp_path)
    assert s.process_folder(folder, lambda pdf, d: SUMMARIZED) == 0
    assert list(folder.iterdir()) == []


def test_missing_date_folder_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "OUT_ROOT", tmp_path)
    assert s.target_folders("10/21/2026") == []


def test_folders_ignore_partial_downloads_and_sort_by_date(tmp_path, monkeypatch):
    monkeypatch.setattr(s, "OUT_ROOT", tmp_path)
    for name in ("10_21_2026", "01_05_2027", "10_21_2026.partial"):
        (tmp_path / name).mkdir()
    assert [p.name for p in s.target_folders(None)] == ["10_21_2026", "01_05_2027"]


def test_long_date_has_no_leading_zero():
    assert s.long_date(s.folder_date("11_04_2026")) == "November 4, 2026"
