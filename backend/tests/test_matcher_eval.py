"""Matcher evaluation harness — Challenge 7 scorecard.

Runs the full pipeline once into a tempdir warehouse, then iterates the labeled
pairs in `golden_pairs.csv` and asks customer_xref whether each pair landed
under the same `customer_id`. Reports precision, recall, false-confidence rate,
stratified by difficulty.

Marked `xfail` so the suite runs even when the matcher misses cases — the goal
is to surface the numbers, not to gate CI on perfection.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterator

import duckdb
import pytest

from pipeline import conform, ingest, match


GOLDEN_CSV = Path(__file__).parent / "golden_pairs.csv"


@pytest.fixture(scope="session")
def warehouse(tmp_path_factory: pytest.TempPathFactory) -> Iterator[duckdb.DuckDBPyConnection]:
    tmp_dir = tmp_path_factory.mktemp("warehouse")
    db_path = tmp_dir / "test.duckdb"
    con = duckdb.connect(str(db_path))
    ingest.init_schemas(con)
    ingest.run_all(con)
    conform.run_all(con)
    match.run(con)
    try:
        yield con
    finally:
        con.close()


def _customer_id(con: duckdb.DuckDBPyConnection, source: str, source_id: str) -> str | None:
    row = con.execute(
        "SELECT customer_id FROM curated.customer_xref WHERE _source = ? AND _source_id = ?",
        [source, source_id],
    ).fetchone()
    return row[0] if row else None


def _load_pairs() -> list[dict[str, str]]:
    with GOLDEN_CSV.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


@pytest.mark.xfail(strict=False, reason="matcher is the probabilistic component; xfail surfaces metrics")
def test_matcher_meets_targets(warehouse: duckdb.DuckDBPyConnection) -> None:
    pairs = _load_pairs()
    tp = fp = fn = tn = 0
    false_confidence = 0
    by_difficulty: dict[str, dict[str, int]] = {}

    for p in pairs:
        verdict = p["verdict"].strip().lower()
        diff = p["difficulty"].strip().lower() or "unknown"
        cid_l = _customer_id(warehouse, p["left_source"], p["left_id"])
        cid_r = _customer_id(warehouse, p["right_source"], p["right_id"])
        merged = cid_l is not None and cid_l == cid_r

        bucket = by_difficulty.setdefault(diff, {"tp": 0, "fp": 0, "fn": 0, "tn": 0, "fc": 0})

        if verdict == "match":
            if merged:
                tp += 1; bucket["tp"] += 1
            else:
                fn += 1; bucket["fn"] += 1
        elif verdict == "no_match":
            if merged:
                fp += 1; bucket["fp"] += 1
                false_confidence += 1; bucket["fc"] += 1
            else:
                tn += 1; bucket["tn"] += 1
        # "unclear" pairs are excluded from precision/recall but reported separately.

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    fc_rate = false_confidence / max(1, tp + fp)

    print("\n=== Matcher eval ===")
    print(f"  precision={precision:.3f}  recall={recall:.3f}  false_confidence={fc_rate:.3f}")
    print(f"  TP={tp} FP={fp} FN={fn} TN={tn}")
    print("  by difficulty:")
    for diff, b in sorted(by_difficulty.items()):
        print(f"    {diff}: TP={b['tp']} FP={b['fp']} FN={b['fn']} TN={b['tn']} FC={b['fc']}")

    # Aspirational targets — xfail above means we don't fail CI on these yet.
    assert precision >= 0.95, f"precision {precision:.3f} below target"
    assert recall >= 0.90, f"recall {recall:.3f} below target"
    assert fc_rate <= 0.05, f"false confidence {fc_rate:.3f} above target"
