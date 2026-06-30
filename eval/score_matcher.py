#!/usr/bin/env python
"""Challenge 7 — The Scorecard. Eval harness for the entity matcher.

Scores resolve.score_pair() against eval/golden_pairs.csv (hand-labelled
match / no_match / unclear, including the boundary cases the few-shot prompt is
built to teach). Reports, stratified by difficulty so easy cases don't dominate:

    precision / recall / F1   for the MATCH decision
    false-confidence rate     = of pairs the matcher called "match" with HIGH
                                confidence (>=0.95), how often it was actually wrong.
                                This is the number the CDO cares about: confident & wrong.

Exits non-zero if any CI threshold is breached, so it gates the pipeline in CI
(.github/workflows/ci.yml). One defensible number for "how good is this".
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import common, resolve  # noqa: E402

# Map a raw score to a 3-way verdict using the live matcher thresholds.
HIGH_CONFIDENCE = 0.95
# CI gates (the defensible single numbers).
GATES = {"match_precision": 0.90, "match_recall": 0.60, "false_confidence_rate": 0.05}


def verdict(score: float) -> str:
    if score >= resolve.AUTO_MERGE:
        return "match"
    if score >= resolve.REVIEW:
        return "unclear"
    return "no_match"


def load_conformed(con) -> dict:
    rows = con.execute(
        "SELECT source_system, source_record_id, full_name, name_norm, email, email_norm, "
        "phone, phone_norm, street, city, state, zip, country, dob, created_at_utc "
        "FROM conformed_customer"
    ).fetchall()
    cols = [d[0] for d in con.description]
    out = {}
    for r in rows:
        d = dict(zip(cols, r))
        out.setdefault((d["source_system"], d["source_record_id"]), d)  # first wins
    return out


def main() -> int:
    pairs_path = Path(__file__).resolve().parent / "golden_pairs.csv"
    pairs = list(csv.DictReader(pairs_path.open()))
    with common.connect(read_only=True) as con:
        recs = load_conformed(con)

    results = []
    for p in pairs:
        a = recs.get((p["a_source"], p["a_id"]))
        b = recs.get((p["b_source"], p["b_id"]))
        if not a or not b:
            print(f"  ! {p['pair_id']}: record not found ({p['a_id']} / {p['b_id']})")
            continue
        score, reasons = resolve.score_pair(a, b)
        pred = verdict(score)
        results.append({**p, "score": score, "pred": pred, "reasons": "; ".join(reasons),
                        "correct": pred == p["label"]})

    _print_results(results)
    metrics = _metrics(results)
    return _gate(metrics)


def _print_results(results):
    print("\n  pair  stratum  label      pred       score  ok  why")
    print("  " + "-" * 92)
    for r in results:
        flag = "✓" if r["correct"] else "✗"
        print(f"  {r['pair_id']:<5} {r['stratum']:<7} {r['label']:<10} {r['pred']:<10} "
              f"{r['score']:.2f}  {flag}  {r['reasons'][:48]}")


def _metrics(results):
    def prf(subset):
        tp = sum(1 for r in subset if r["label"] == "match" and r["pred"] == "match")
        fp = sum(1 for r in subset if r["label"] != "match" and r["pred"] == "match")
        fn = sum(1 for r in subset if r["label"] == "match" and r["pred"] != "match")
        prec = tp / (tp + fp) if (tp + fp) else 1.0
        rec = tp / (tp + fn) if (tp + fn) else 1.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        return prec, rec, f1, tp, fp, fn

    print("\n  Stratified (so easy cases don't dominate the headline number):")
    print("  stratum   n   precision  recall   F1")
    strata = defaultdict(list)
    for r in results:
        strata[r["stratum"]].append(r)
    for s in ["easy", "medium", "hard"]:
        if strata[s]:
            p, rec, f1, *_ = prf(strata[s])
            print(f"  {s:<8} {len(strata[s]):>2}    {p:.2f}      {rec:.2f}    {f1:.2f}")

    prec, rec, f1, tp, fp, fn = prf(results)
    # false-confidence: high-confidence predictions that were wrong
    hi = [r for r in results if r["pred"] == "match" and r["score"] >= HIGH_CONFIDENCE]
    hi_wrong = [r for r in hi if r["label"] != "match"]
    fcr = len(hi_wrong) / len(hi) if hi else 0.0
    accuracy = sum(r["correct"] for r in results) / len(results)

    print(f"\n  OVERALL  n={len(results)}")
    print(f"    match precision        {prec:.3f}   (TP={tp} FP={fp})")
    print(f"    match recall           {rec:.3f}   (FN={fn})")
    print(f"    match F1               {f1:.3f}")
    print(f"    3-way accuracy         {accuracy:.3f}")
    print(f"    false-confidence rate  {fcr:.3f}   ({len(hi_wrong)}/{len(hi)} high-conf calls wrong)")
    if fn:
        print("    known misses (recall):", ", ".join(r["pair_id"] for r in results
              if r["label"] == "match" and r["pred"] != "match"))
    return {"match_precision": prec, "match_recall": rec, "false_confidence_rate": fcr}


def _gate(metrics) -> int:
    print("\n  CI gates:")
    failed = False
    for k, threshold in GATES.items():
        v = metrics[k]
        ok = v <= threshold if k == "false_confidence_rate" else v >= threshold
        cmp = "<=" if k == "false_confidence_rate" else ">="
        print(f"    {'PASS' if ok else 'FAIL'}  {k} {v:.3f} {cmp} {threshold}")
        failed |= not ok
    print("\n  RESULT:", "FAIL — matcher regressed" if failed else "PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
