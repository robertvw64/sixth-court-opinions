import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fetch_opinions as f

here = Path(__file__).parent
pdfs = sorted((here.parents[1] / "Orders and Opinions for October 9, 2026").glob("*.pdf"))
if len(pdfs) != 4:
    print("SKIP: sample PDFs not present"); sys.exit(0)
order = iter(pdfs)
class R:
    def __init__(s, text=None, content=None): s.text, s.content = text, content
def fake_get(url):
    if "Docket.aspx" in url:
        return R(text=(here / "fixture_docket.html").read_text(encoding="utf-8"))
    return R(content=next(order).read_bytes())
f.get = fake_get
f.OUT_ROOT = Path(tempfile.mkdtemp()) / "opinions"
assert f.save_date("10/09/2026") == 4
out = f.OUT_ROOT / "Orders and Opinions for October 9, 2026"
print(sorted(p.name for p in out.iterdir()))
print((out / "index.md").read_text())
assert f.save_date("10/09/2026") == 0  # second run skips
print("OK")
