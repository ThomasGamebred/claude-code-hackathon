"""Challenge 4 — The Customer. Resolve the conformed rows into golden records.

Pipeline:
    block   -> generate candidate pairs that share a strong key (phone/email/name+dob)
               so we never compare all N^2 rows.
    score   -> explainable feature score in [0,1] per pair, encoding the rules in
               matcher_prompt.md (shared strong id near-decisive; name alone weak;
               DOB conflict is a hard negative).
    decide  -> AUTO_MERGE >= 0.90, REVIEW in [0.72, 0.90), else NO_MATCH.
    cluster -> union-find over AUTO_MERGE edges.
    survive -> one golden record per cluster, field-level provenance + confidence.

The scorer is deterministic and unit-testable; the eval harness (eval/) scores it
against a labelled golden set and reports precision / recall / false-confidence rate.
"""
from __future__ import annotations

import json
from collections import defaultdict

from . import common

AUTO_MERGE = 0.90
REVIEW = 0.72

# Trust order for survivorship: who do we believe when fields conflict?
# Customer-entered, well-cased sources beat uppercased/truncated legacy dumps.
SOURCE_TRUST = {
    "crm": 6, "ecommerce": 5, "loyalty": 4,
    "acq_sunset": 3, "pos": 2, "acq_rheinland": 2, "acq_northwind": 1,
}


# --------------------------------------------------------------- string similarity
def jaro_winkler(s1: str, s2: str) -> float:
    """Pure-stdlib Jaro-Winkler. No external deps (keeps the runtime tiny)."""
    if s1 == s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    max_dist = max(len(s1), len(s2)) // 2 - 1
    s1_m = [False] * len(s1)
    s2_m = [False] * len(s2)
    matches = 0
    for i, c in enumerate(s1):
        lo, hi = max(0, i - max_dist), min(i + max_dist + 1, len(s2))
        for j in range(lo, hi):
            if not s2_m[j] and s2[j] == c:
                s1_m[i] = s2_m[j] = True
                matches += 1
                break
    if not matches:
        return 0.0
    t = k = 0
    for i in range(len(s1)):
        if s1_m[i]:
            while not s2_m[k]:
                k += 1
            if s1[i] != s2[k]:
                t += 1
            k += 1
    t /= 2
    jaro = (matches / len(s1) + matches / len(s2) + (matches - t) / matches) / 3
    prefix = 0
    for a, b in zip(s1[:4], s2[:4]):
        if a == b:
            prefix += 1
        else:
            break
    return jaro + prefix * 0.1 * (1 - jaro)


# --------------------------------------------------------------- pairwise scoring
def score_pair(a: dict, b: dict) -> tuple[float, list[str]]:
    """Return (score, reasons). Encodes matcher_prompt.md rules."""
    reasons: list[str] = []
    score = 0.0

    same_phone = a["phone_norm"] and a["phone_norm"] == b["phone_norm"]
    same_email = a["email_norm"] and a["email_norm"] == b["email_norm"]
    name_sim = jaro_winkler(a["name_norm"], b["name_norm"]) if a["name_norm"] and b["name_norm"] else 0.0

    # Rule 4: a clean DOB conflict is a hard negative (allow obvious digit-swap noise).
    if a["dob"] and b["dob"] and a["dob"] != b["dob"]:
        if abs((a["dob"] - b["dob"]).days) > 2:
            reasons.append(f"DOB conflict {a['dob']} vs {b['dob']}")
            return 0.05, reasons
    same_dob = a["dob"] and a["dob"] == b["dob"]

    # Rule 1: shared strong identifier is near-decisive.
    if same_phone:
        score = max(score, 0.80); reasons.append("same phone")
    if same_email:
        score = max(score, 0.84); reasons.append("same email")
    # corroboration stacks
    if same_phone and same_email:
        score = 0.98
    if (same_phone or same_email) and same_dob:
        score = max(score, 0.96); reasons.append("same DOB corroborates")
    if (same_phone or same_email) and name_sim >= 0.80:
        score = max(score, 0.95); reasons.append(f"name agrees ({name_sim:.2f})")

    # Rule 2/3: without a strong id, demand name + a second weak signal.
    if not (same_phone or same_email):
        if same_dob and name_sim >= 0.88:
            score = max(score, 0.86); reasons.append(f"same DOB + close name ({name_sim:.2f})")
        elif name_sim >= 0.93 and a["zip"] and a["zip"] == b["zip"]:
            score = max(score, 0.74); reasons.append(f"very close name + same zip ({name_sim:.2f})")
        elif name_sim >= 0.90 and a["city"] and a["city"] == b["city"]:
            score = max(score, 0.55); reasons.append("close name + same city (weak)")
        else:
            reasons.append(f"name_sim={name_sim:.2f}, no strong id")
    return round(score, 4), reasons


# --------------------------------------------------------------- blocking
def _block_keys(r: dict) -> list[str]:
    keys = []
    if r["phone_norm"]:
        keys.append(f"ph:{r['phone_norm']}")
    if r["email_norm"]:
        keys.append(f"em:{r['email_norm']}")
    if r["name_norm"]:
        toks = r["name_norm"].split()
        if toks:                       # surname token + zip / dob, to catch id-less dupes
            keys.append(f"nz:{toks[0]}:{r['zip'] or ''}")
            if r["dob"]:
                keys.append(f"nd:{toks[0]}:{r['dob']}")
    return keys


# --------------------------------------------------------------- union-find
class _UF:
    def __init__(self): self.p = {}
    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]; x = self.p[x]
        return x
    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


# --------------------------------------------------------------- survivorship
def _pick(members: list[dict], field: str, *, prefer_recent=False):
    """Choose the surviving value for `field` and report (value, confidence, source).

    Confidence = share of non-null members that agree with the chosen value."""
    vals = [(m, m.get(field)) for m in members if m.get(field) not in (None, "", "null")]
    if not vals:
        return None, 0.0, None
    # tally agreement (case-insensitive for strings)
    norm = lambda v: str(v).strip().lower()
    tally = defaultdict(list)
    for m, v in vals:
        tally[norm(v)].append((m, v))
    # winner: most agreement, tie-broken by recency or source trust
    def rank(item):
        _, group = item
        recency = max((str(g[0].get("created_at_utc") or "") for g in group)) if prefer_recent else ""
        trust = max(SOURCE_TRUST.get(g[0]["source_system"], 0) for g in group)
        # prefer longer, properly-cased names (more complete)
        completeness = max(len(str(g[1])) for g in group) if field == "full_name" else 0
        return (len(group), recency, trust, completeness)
    best_key, best_group = max(tally.items(), key=rank)
    chosen_m, chosen_v = max(best_group, key=lambda g: (SOURCE_TRUST.get(g[0]["source_system"], 0), len(str(g[1]))))
    confidence = round(len(best_group) / len(vals), 3)
    return chosen_v, confidence, chosen_m["source_system"]


def build_golden(members: list[dict], edge_scores: list[float]) -> dict:
    fields_recent = {"street", "city", "state", "zip", "phone", "email"}
    golden = {"member_count": len(members)}
    provenance, confidence = {}, {}
    for f in ["full_name", "email", "phone", "street", "city", "state", "zip", "dob", "country"]:
        v, c, src = _pick(members, f, prefer_recent=f in fields_recent)
        golden[f] = v
        provenance[f] = src
        confidence[f] = c
    # cluster match_confidence: weakest connecting edge (a chain is only as strong
    # as its weakest auto-merge link). Singletons are trivially certain.
    golden["match_confidence"] = round(min(edge_scores), 3) if edge_scores else 1.0
    golden["field_provenance"] = provenance
    golden["field_confidence"] = confidence
    golden["member_lineage_ids"] = [m["lineage_id"] for m in members]
    golden["member_sources"] = sorted({m["source_system"] for m in members})
    return golden


# --------------------------------------------------------------- driver
def run(con) -> dict:
    rows = [dict(zip([d[0] for d in con.description], r)) for r in con.execute(
        "SELECT lineage_id, source_system, source_record_id, full_name, name_norm, "
        "email, email_norm, phone, phone_norm, street, city, state, zip, country, dob, "
        "created_at_utc FROM conformed_customer"
    ).fetchall()]
    by_id = {r["lineage_id"]: r for r in rows}

    # block -> candidate pairs
    buckets: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        for k in _block_keys(r):
            buckets[k].append(r["lineage_id"])
    cand = set()
    for ids in buckets.values():
        if len(ids) < 2 or len(ids) > 40:   # giant buckets are noise (e.g. empty zip)
            continue
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                cand.add(tuple(sorted((ids[i], ids[j]))))

    # score + decide
    uf = _UF()
    for r in rows:
        uf.find(r["lineage_id"])
    edges = []          # (a, b, score, reasons)
    review = []
    for a_id, b_id in cand:
        s, reasons = score_pair(by_id[a_id], by_id[b_id])
        if s >= AUTO_MERGE:
            uf.union(a_id, b_id)
            edges.append((a_id, b_id, s, reasons))
        elif s >= REVIEW:
            review.append((a_id, b_id, s, reasons))

    # cluster + survivorship
    clusters: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        clusters[uf.find(r["lineage_id"])].append(r["lineage_id"])
    cluster_edges: dict[str, list[float]] = defaultdict(list)
    for a_id, b_id, s, _ in edges:
        cluster_edges[uf.find(a_id)].append(s)

    _write_curated(con, clusters, cluster_edges, by_id)
    _write_review(con, review, by_id)

    merged = sum(1 for ids in clusters.values() if len(ids) > 1)
    return {
        "input_rows": len(rows),
        "golden_records": len(clusters),
        "clusters_merged_from_multiple": merged,
        "rows_collapsed": len(rows) - len(clusters),
        "review_queue": len(review),
    }


def _write_curated(con, clusters, cluster_edges, by_id):
    con.execute("""
        CREATE OR REPLACE TABLE curated_customer (
            golden_id VARCHAR, full_name VARCHAR, email VARCHAR, phone VARCHAR,
            street VARCHAR, city VARCHAR, state VARCHAR, zip VARCHAR, country VARCHAR,
            dob DATE, match_confidence DOUBLE, member_count INTEGER,
            member_sources VARCHAR, member_lineage_ids JSON,
            field_provenance JSON, field_confidence JSON
        );
    """)
    for root, ids in sorted(clusters.items()):
        members = [by_id[i] for i in ids]
        g = build_golden(members, cluster_edges.get(root, []))
        golden_id = "G-" + root.split(":")[-1][:12]
        con.execute(
            "INSERT INTO curated_customer VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [golden_id, g["full_name"], g["email"], g["phone"], g["street"], g["city"],
             g["state"], g["zip"], g["country"], g["dob"], g["match_confidence"],
             g["member_count"], ",".join(g["member_sources"]),
             json.dumps(g["member_lineage_ids"]), json.dumps(g["field_provenance"]),
             json.dumps(g["field_confidence"])],
        )


def _write_review(con, review, by_id):
    con.execute("""
        CREATE OR REPLACE TABLE match_review_queue (
            a_lineage VARCHAR, b_lineage VARCHAR, score DOUBLE, reasons VARCHAR,
            a_name VARCHAR, b_name VARCHAR
        );
    """)
    for a_id, b_id, s, reasons in sorted(review, key=lambda x: -x[2]):
        con.execute("INSERT INTO match_review_queue VALUES (?,?,?,?,?,?)",
                    [a_id, b_id, s, "; ".join(reasons),
                     by_id[a_id]["full_name"], by_id[b_id]["full_name"]])


if __name__ == "__main__":
    with common.connect() as con:
        print(json.dumps(run(con), indent=2))
