import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fetch_opinions as f

here = Path(__file__).parent
dates = f.listed_dates((here / "fixture_list.html").read_text(encoding="utf-8"))
print("dates:", dates)
assert "10/09/2026" in dates
items = f.parse_docket((here / "fixture_docket.html").read_text(encoding="utf-8"))
for it in items:
    print(it["section"], "|", it["case"], "|", it["style"], "|", it["origin"], "|", it["disposition"], "|", it["description"], "|", it["judges"])
assert [i["case"] for i in items] == ["06-26-00046-CV", "06-26-00087-CV", "06-26-00160-CR", "06-26-00161-CR"]
assert f.folder_name("10/09/2026") == "Orders and Opinions for October 9, 2026"
print("OK")
