"""Head-to-head evaluation of the approaches on a labelled corpus.

Labels come from corpus/sources.yaml (shipped documents are `good` or
`shipped`), the E0 fixtures, and every product of `mutate.MUTATIONS` applied
to each good document (`bad`, reason = mutation name). Each document is
rendered once and cached by content hash. Output: eval/results.json, with a
per-document verdict table and a per-approach confusion summary.
"""
from __future__ import annotations

import hashlib
import json
import os
import time

import yaml

from . import mutate, profile as P, render as R
from .approaches import APPROACHES, run_approach
from .checks import structural
from .types import HarnessError

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
E0 = "corpus/u1-vt-graphs/fixtures/rendered"


def build_labels(sources_path: str = "corpus/sources.yaml", mutations: bool = True) -> list[dict]:
    cfg = yaml.safe_load(open(sources_path))
    docs = []
    u1 = "profiles/u1-vt-graphs.yaml"
    for n, lab in (("fixed-worksheet", "good"), ("fixed-key", "good"),
                   ("prefix-worksheet", "bad"), ("prefix-key", "bad")):
        docs.append({"id": f"e0-{n}", "path": f"{E0}/{n}.html", "profile": u1, "label": lab,
                     "reason": "E0 regression fixture" if lab == "bad" else "E0 shipped fixture",
                     "mutation": None, "parent": None})
    for slug, d in cfg["documents"].items():
        if slug.startswith("hp-u1-vt"):
            continue              # byte-identical to the E0 fixed fixtures
        docs.append({"id": slug, "path": f"corpus/{slug}/source.html",
                     "profile": f"corpus/{slug}/profile.yaml", "label": d["label"],
                     "reason": "curriculum document", "mutation": None, "parent": None})
    if mutations:
        out_dir = "eval/mutants"
        os.makedirs(out_dir, exist_ok=True)
        for base in [d for d in docs if d["label"] == "good"]:
            src = open(base["path"], encoding="utf-8").read()
            for name, fn in mutate.MUTATIONS.items():
                mutated = fn(src)
                if mutated is None or mutated == src:
                    continue
                p = os.path.join(out_dir, f"{base['id']}--{name}.html")
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(mutated)
                docs.append({"id": f"{base['id']}--{name}", "path": p, "profile": base["profile"],
                             "label": "bad", "reason": f"mutation {name}", "mutation": name,
                             "parent": base["id"]})
    return docs


def render_cached(path: str, cache_dir: str):
    h = hashlib.sha1(open(path, "rb").read()).hexdigest()[:16]
    d = os.path.join(cache_dir, h)
    geom = os.path.join(d, "geometry.json")
    if os.path.exists(geom):
        return R.load_artifacts(geom), 0.0
    t = time.perf_counter()
    art = R.render(path, d)
    return art, time.perf_counter() - t


def run_eval(labels_path: str = "eval/labels.yaml", out_path: str = "eval/results.json",
             cache_dir: str = "eval/cache", approaches=APPROACHES) -> int:
    docs = build_labels()
    with open(labels_path, "w") as fh:
        yaml.safe_dump(docs, fh, sort_keys=False)
    rows = []
    for d in docs:
        row = {**d, "approaches": {}}
        try:
            art, rsec = render_cached(d["path"], cache_dir)
        except HarnessError as e:
            row["error"] = str(e)
            rows.append(row)
            print(f"{d['id']:<40} RENDER ERROR {e}")
            continue
        row["page_count"] = art.page_count
        row["render_seconds"] = round(rsec, 2)
        prof = P.load(d["profile"])
        golden = None
        if d["parent"]:
            parent = next(x for x in docs if x["id"] == d["parent"])
            golden = os.path.dirname(render_cached(parent["path"], cache_dir)[0].pdf_path)
        for a in approaches:
            try:
                res = run_approach(a, art, prof, golden)
                if a == "gates" and d["parent"]:
                    # the structural gate is a before/after invariant: it needs
                    # the parent's fingerprint, which a mutant has
                    res.findings += structural.compare(structural.fingerprint(parent["path"]),
                                                       structural.fingerprint(d["path"]))
                    if any(f.failed for f in res.findings):
                        res.verdict = "fail"
                row["approaches"][a] = {"verdict": res.verdict, "hard": res.hard_ids,
                                        "checks": sorted(res.hard_checks),
                                        "seconds": round(res.seconds, 4)}
            except Exception as e:  # an approach crashing is a result, not an abort
                row["approaches"][a] = {"verdict": "error", "hard": [], "checks": [],
                                        "seconds": 0.0, "error": repr(e)}
        rows.append(row)
        print(f"{d['id']:<40} {d['label']:<8} p{art.page_count:<3} " +
              "  ".join(f"{a}={row['approaches'][a]['verdict']}" for a in approaches))
    summary = summarise(rows, approaches)
    with open(out_path, "w") as fh:
        json.dump({"schema": 1, "generated": time.strftime("%Y-%m-%d %H:%M"),
                   "documents": rows, "summary": summary}, fh, indent=1)
    print(json.dumps(summary, indent=1))
    return 0


def summarise(rows: list[dict], approaches) -> dict:
    out = {}
    for a in approaches:
        tp = fp = fn = tn = 0
        ship_fail = ship_n = 0
        secs = []
        mutation_hits: dict[str, list] = {}
        for r in rows:
            res = r["approaches"].get(a)
            if not res:
                continue
            secs.append(res["seconds"])
            failed = res["verdict"] == "fail"
            if r["label"] == "bad":
                tp += failed
                fn += not failed
                if r["mutation"]:
                    mutation_hits.setdefault(r["mutation"], []).append(failed)
            elif r["label"] == "good":
                fp += failed
                tn += not failed
            elif r["label"] == "shipped":
                ship_n += 1
                ship_fail += failed
        prec = tp / (tp + fp) if tp + fp else None
        rec = tp / (tp + fn) if tp + fn else None
        out[a] = {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
                  "precision": None if prec is None else round(prec, 3),
                  "recall": None if rec is None else round(rec, 3),
                  "shipped_docs": ship_n, "shipped_flagged": ship_fail,
                  "mean_seconds": round(sum(secs) / len(secs), 4) if secs else None,
                  "mutation_detection": {m: f"{sum(v)}/{len(v)}" for m, v in sorted(mutation_hits.items())}}
    # the winner: zero false fails on labelled-good documents, then highest recall,
    # then fewest shipped documents flagged, then fastest
    ranked = sorted(out.items(), key=lambda kv: (kv[1]["fp"], -(kv[1]["recall"] or 0),
                                                 kv[1]["shipped_flagged"], kv[1]["mean_seconds"] or 0))
    out["winner"] = ranked[0][0] if ranked else None
    return out
