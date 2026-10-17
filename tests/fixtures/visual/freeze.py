"""Re-freeze the visual fixtures' geometry. Run from the repo root:
    uv run python tests/fixtures/visual/freeze.py
Commit the regenerated *.geometry.json files with any render.py change."""
import json
import tempfile
from pathlib import Path

from printfit import render as R

HERE = Path(__file__).parent
for name in ("labels", "arrows"):
    art = R.render(str(HERE / f"{name}.html"), tempfile.mkdtemp(prefix="pf-freeze-"))
    out = HERE / f"{name}.geometry.json"
    R.save_artifacts(art, str(out))
    # keep machine paths out of the committed fixture, like the other frozen fixtures
    d = json.loads(out.read_text())
    d["pdf_path"] = "render.pdf"
    d["page_png_paths"] = [Path(p).name for p in d["page_png_paths"]]
    d["chrome_path"] = "chrome"
    out.write_text(json.dumps(d, indent=1))
    print(name, len(art.dom_geometry.get("figure_marks", [])), "figures")
