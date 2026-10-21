#!/usr/bin/env python3
"""Download released orders and opinions from the Texas Sixth Court of Appeals.

For each release date listed at
https://search.txcourts.gov/DocketSrch.aspx?coa=coa06 this script opens the
"Released Orders & Opinions for <date>" page, downloads every PDF in the four
lists (Civil Causes Decided, Civil Orders, Criminal Causes Decided, Criminal
Orders) and saves them to:

    opinions/Orders and Opinions for <Month D, YYYY>/

along with an index.md describing each case. Dates whose folder already exists
are skipped, so the script is safe to run repeatedly.

Usage:
    python fetch_opinions.py                  # every listed date not yet saved
    python fetch_opinions.py --date 10/09/2026  # one specific date
"""
import argparse
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://search.txcourts.gov/"
LIST_URL = BASE + "DocketSrch.aspx?coa=coa06"
DOCKET_URL = BASE + "Docket.aspx?coa=coa06&FullDate={date}"
OUT_ROOT = Path(__file__).resolve().parent / "opinions"
DELAY = 2  # seconds between requests, to keep the load on the court's site light

session = requests.Session()
session.headers["User-Agent"] = (
    "Mozilla/5.0 (personal daily download of Sixth Court of Appeals opinions)"
)


def get(url):
    time.sleep(DELAY)
    r = session.get(url, timeout=60)
    r.raise_for_status()
    return r


def folder_name(date_str):
    d = datetime.strptime(date_str, "%m/%d/%Y")
    return f"Orders and Opinions for {d.strftime('%B')} {d.day}, {d.year}"


def listed_dates(html):
    soup = BeautifulSoup(html, "html.parser")
    dates = []
    for a in soup.find_all("a", href=True):
        m = re.search(r"FullDate=(\d{1,2}/\d{1,2}/\d{4})", a["href"])
        if m and m.group(1) not in dates:
            dates.append(m.group(1))
    return dates


def parse_docket(html):
    """Return a list of dicts, one per PDF link, grouped by section heading."""
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for h3 in soup.find_all("h3"):
        section = " ".join(h3.get_text(" ", strip=True).split())
        grid = h3.find_next("table", class_="rgMasterTable")
        if grid is None:
            continue
        tbody = grid.find("tbody")
        for row in tbody.find_all("tr", recursive=False) if tbody else []:
            cells = row.find_all("td", recursive=False)
            if len(cells) < 4:
                continue  # "No records to display."
            case_link = cells[0].find("a", href=re.compile(r"Case\.aspx"))
            case_no = case_link.get_text(strip=True) if case_link else "unknown-case"
            style_b = cells[1].find("span")
            style = style_b.get_text(" ", strip=True) if style_b else cells[1].get_text(" ", strip=True)
            origin = cells[1].get_text(" ", strip=True).replace(style, "", 1).strip()
            disposition = cells[2].get_text(" ", strip=True)
            judges = ", ".join(s.strip() for s in cells[3].stripped_strings)
            for doc_row in cells[0].select("table.docGrid tr"):
                pdf = doc_row.find("a", href=re.compile(r"SearchMedia\.aspx"))
                if not pdf:
                    continue
                desc = doc_row.find("td").get_text(" ", strip=True)
                items.append({
                    "section": section, "case": case_no, "style": style,
                    "origin": origin, "disposition": disposition,
                    "judges": judges, "description": desc,
                    "url": urljoin(BASE, pdf["href"]),
                })
    return items


def save_date(date_str, force=False):
    out = OUT_ROOT / folder_name(date_str)
    if out.exists() and not force:
        print(f"{date_str}: already saved, skipping")
        return 0
    items = parse_docket(get(DOCKET_URL.format(date=date_str)).text)
    if not items:
        print(f"{date_str}: no PDFs listed")
        return 0
    tmp = out.with_name(out.name + ".partial")
    tmp.mkdir(parents=True, exist_ok=True)
    used = {}
    lines = [f"# {out.name}", "", f"Source: {DOCKET_URL.format(date=date_str)}", ""]
    current = None
    for it in items:
        n = used.get(it["case"], 0) + 1
        used[it["case"]] = n
        fname = f"{it['case']}.pdf" if n == 1 else f"{it['case']} ({n}).pdf"
        r = get(it["url"])
        if not r.content.startswith(b"%PDF"):
            raise RuntimeError(f"{it['url']} did not return a PDF")
        (tmp / fname).write_bytes(r.content)
        if it["section"] != current:
            if current is not None:
                lines.append("")
            current = it["section"]
            lines += [f"## {current}", ""]
        lines.append(
            f"- **{it['case']}** — {it['style']} ({it['origin']}). "
            f"{it['disposition']}. {it['description']}. Panel: {it['judges']}. "
            f"File: `{fname}`"
        )
        print(f"{date_str}: saved {fname}")
    (tmp / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if out.exists():
        import shutil
        shutil.rmtree(out)
    tmp.rename(out)
    return len(items)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="MM/DD/YYYY; default is every listed date not yet saved")
    ap.add_argument("--force", action="store_true", help="re-download even if saved")
    args = ap.parse_args()
    if args.date:
        dates = [datetime.strptime(args.date, "%m/%d/%Y").strftime("%m/%d/%Y")]
    else:
        dates = listed_dates(get(LIST_URL).text)
        print("Listed dates:", ", ".join(dates) or "none")
    total = sum(save_date(d, args.force) for d in dates)
    print(f"Done: {total} new PDF(s)")


if __name__ == "__main__":
    sys.exit(main())
