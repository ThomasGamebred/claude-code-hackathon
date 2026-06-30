"""Identity resolution: deterministic + fuzzy, with field-level survivorship.

Two passes:
  1) Deterministic: union-find merge on exact normalized email, exact phone E.164,
     and the loyalty.pos_customer_id <-> pos.cust_id foreign key.
  2) Fuzzy: blocked by (last_initial, region, birth_year). Pairwise score from
     rapidfuzz over name + street + city, with phone/email exact-match boosts.

Survivorship is field-level. Each field on the master records `<field>_source`
and `<field>_confidence`. `customer_id` is uuid5 over the strongest available
key (email, phone, or normalized name + dob) so reruns are stable.
"""
from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any

import duckdb
from rapidfuzz import fuzz

from pipeline.normalize import hash_pii, utc_now


NS = uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")

AUTO_MERGE = 0.90
REVIEW_LOW = 0.70

# Higher rank wins ties in survivorship.
SOURCE_RANK: dict[str, int] = {
    "ecommerce": 7,
    "loyalty": 6,
    "crm": 5,
    "pos": 4,
    "acq_sunset": 3,
    "acq_rheinland": 3,
    "acq_northwind": 2,
}


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, x: str) -> None:
        if x not in self.parent:
            self.parent[x] = x

    def find(self, x: str) -> str:
        self.add(x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb

    def groups(self) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {}
        for node in list(self.parent.keys()):
            root = self.find(node)
            groups.setdefault(root, []).append(node)
        return groups


def _key(source: str, source_id: str) -> str:
    return f"{source}::{source_id}"


def _load_conformed(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    cols = (
        "_source", "_source_id", "_source_row", "first_name", "last_name",
        "full_name_normalized", "email_normalized", "phone_e164", "phone_ext",
        "street", "city", "region", "postal_code", "country", "birth_date",
        "created_at_utc", "field_quality_flags",
    )
    rows = con.execute(
        f"SELECT {', '.join(cols)} FROM conformed.customer"
    ).fetchall()
    return [dict(zip(cols, r)) for r in rows]


def _deterministic_pass(records: list[dict[str, Any]]) -> tuple[_UnionFind, dict[str, list[str]]]:
    uf = _UnionFind()
    by_email: dict[str, list[str]] = {}
    by_phone: dict[str, list[str]] = {}
    pos_by_custid: dict[str, list[str]] = {}

    for r in records:
        k = _key(r["_source"], r["_source_id"])
        uf.add(k)
        if r["email_normalized"]:
            by_email.setdefault(r["email_normalized"], []).append(k)
        if r["phone_e164"]:
            by_phone.setdefault(r["phone_e164"], []).append(k)
        if r["_source"] == "pos":
            cust_id = str(r["_source_id"]).split(":", 1)[0]
            pos_by_custid.setdefault(cust_id, []).append(k)

    # Loyalty FK pull from raw — the conform layer does not propagate the FK.
    # We re-read from raw.loyalty so the matcher can apply it.

    for ks in by_email.values():
        for k in ks[1:]:
            uf.union(ks[0], k)
    for ks in by_phone.values():
        for k in ks[1:]:
            uf.union(ks[0], k)

    return uf, pos_by_custid


def _apply_loyalty_fk(
    con: duckdb.DuckDBPyConnection,
    uf: _UnionFind,
    pos_by_custid: dict[str, list[str]],
) -> None:
    rows = con.execute(
        "SELECT member_id, pos_customer_id FROM raw.loyalty"
    ).fetchall()
    for member_id, fk in rows:
        if not fk:
            continue
        fk_s = str(fk).strip()
        if fk_s in ("", "NULL", "999999"):
            continue
        loyalty_key = _key("loyalty", member_id)
        for pos_key in pos_by_custid.get(fk_s, []):
            uf.union(loyalty_key, pos_key)


# --- Fuzzy features ---------------------------------------------------------

def _name_score(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    return fuzz.token_set_ratio(a, b) / 100.0


def _street_score(a: dict[str, Any], b: dict[str, Any]) -> float:
    s1, s2 = a.get("street"), b.get("street")
    if not s1 or not s2:
        return 0.0
    score = fuzz.token_set_ratio(s1.lower(), s2.lower()) / 100.0
    if a.get("postal_code") and a.get("postal_code") == b.get("postal_code"):
        score = min(1.0, score + 0.1)
    return score


def _phone_score(a: dict[str, Any], b: dict[str, Any]) -> float:
    return 1.0 if a.get("phone_e164") and a.get("phone_e164") == b.get("phone_e164") else 0.0


def _email_score(a: dict[str, Any], b: dict[str, Any]) -> float:
    e1, e2 = a.get("email_normalized"), b.get("email_normalized")
    if not e1 or not e2:
        return 0.0
    if e1 == e2:
        return 1.0
    d1 = e1.rsplit("@", 1)[-1]
    d2 = e2.rsplit("@", 1)[-1]
    return 0.1 if d1 == d2 else 0.0


def _dob_score(a: dict[str, Any], b: dict[str, Any]) -> float:
    d1, d2 = a.get("birth_date"), b.get("birth_date")
    if not d1 or not d2:
        return 0.0
    if d1 == d2:
        return 1.0
    if isinstance(d1, date) and isinstance(d2, date) and d1.year == d2.year:
        return 0.5
    return 0.0


def _score_pair(a: dict[str, Any], b: dict[str, Any]) -> tuple[float, dict[str, float]]:
    name = _name_score(a.get("full_name_normalized"), b.get("full_name_normalized"))
    addr = _street_score(a, b)
    phone = _phone_score(a, b)
    email = _email_score(a, b)
    dob = _dob_score(a, b)

    score = 0.30 * name + 0.20 * addr + 0.25 * phone + 0.20 * email + 0.05 * dob

    # Headline-case boosts: a strong identifier match plus an okay name is enough.
    if (phone == 1.0 or email == 1.0) and name >= 0.6:
        score = max(score, 0.92)
    if phone == 1.0 and email == 1.0:
        score = max(score, 0.98)

    return score, {
        "name": name, "address": addr, "phone": phone, "email": email, "dob": dob,
    }


def _fuzzy_pass(records: list[dict[str, Any]], uf: _UnionFind) -> list[dict[str, Any]]:
    """Returns the list of review pairs (0.70 <= score < 0.90)."""
    blocks: dict[tuple[str, str, str], list[int]] = {}
    for i, r in enumerate(records):
        last = (r.get("last_name") or "").strip()
        region = (r.get("region") or "").strip()
        bd = r.get("birth_date")
        year = str(bd.year) if isinstance(bd, date) else ""
        if not last or not region or not year:
            continue
        key = (last[:1].lower(), region.upper(), year)
        blocks.setdefault(key, []).append(i)

    reviews: list[dict[str, Any]] = []
    for idxs in blocks.values():
        if len(idxs) < 2:
            continue
        for ii in range(len(idxs)):
            for jj in range(ii + 1, len(idxs)):
                a, b = records[idxs[ii]], records[idxs[jj]]
                ka = _key(a["_source"], a["_source_id"])
                kb = _key(b["_source"], b["_source_id"])
                if uf.find(ka) == uf.find(kb):
                    continue
                score, features = _score_pair(a, b)
                if score >= AUTO_MERGE:
                    uf.union(ka, kb)
                elif score >= REVIEW_LOW:
                    reviews.append({
                        "left": ka, "right": kb, "score": score, "features": features,
                    })
    return reviews


# --- Survivorship -----------------------------------------------------------

def _pick_field(
    members: list[dict[str, Any]],
    field: str,
    *,
    prefer_longest: bool = False,
) -> tuple[Any, str | None, float]:
    """Return (value, source, confidence) for the chosen field."""
    candidates = [(m, m.get(field)) for m in members if m.get(field) not in (None, "")]
    if not candidates:
        return None, None, 0.0

    if prefer_longest:
        candidates.sort(key=lambda mv: (len(str(mv[1])), SOURCE_RANK.get(mv[0]["_source"], 0)), reverse=True)
    else:
        candidates.sort(key=lambda mv: SOURCE_RANK.get(mv[0]["_source"], 0), reverse=True)

    chosen_member, value = candidates[0]
    distinct = {str(v) for _, v in candidates}
    confidence = 1.0 if len(distinct) == 1 else max(0.5, 1.0 - 0.1 * (len(distinct) - 1))
    return value, chosen_member["_source"], confidence


def _stable_customer_id(members: list[dict[str, Any]]) -> str:
    # Prefer the strongest natural key for stability.
    emails = sorted({m["email_normalized"] for m in members if m.get("email_normalized")})
    phones = sorted({m["phone_e164"] for m in members if m.get("phone_e164")})
    if emails:
        return str(uuid.uuid5(NS, "email:" + emails[0]))
    if phones:
        return str(uuid.uuid5(NS, "phone:" + phones[0]))
    names = sorted({m["full_name_normalized"] for m in members if m.get("full_name_normalized")})
    dobs = sorted({str(m["birth_date"]) for m in members if m.get("birth_date")})
    seed = "|".join(names) + "|" + "|".join(dobs)
    if seed.strip("|"):
        return str(uuid.uuid5(NS, "namedob:" + seed))
    # Last resort: the sorted member-key tuple, still deterministic.
    keys = sorted(_key(m["_source"], m["_source_id"]) for m in members)
    return str(uuid.uuid5(NS, "keys:" + "|".join(keys)))


def _street_token(s: str | None) -> str | None:
    if not s:
        return None
    h = hash_pii(s.lower().strip())
    return h[:16] if h else None


def _build_master(members: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    cid = _stable_customer_id(members)
    first, first_src, first_conf = _pick_field(members, "first_name", prefer_longest=True)
    last, last_src, last_conf = _pick_field(members, "last_name", prefer_longest=True)
    full_norm, full_src, full_conf = _pick_field(members, "full_name_normalized", prefer_longest=True)
    email, email_src, email_conf = _pick_field(members, "email_normalized")
    phone, phone_src, phone_conf = _pick_field(members, "phone_e164")
    street, street_src, street_conf = _pick_field(members, "street", prefer_longest=True)
    city, city_src, _ = _pick_field(members, "city")
    region, region_src, _ = _pick_field(members, "region")
    zip_, zip_src, _ = _pick_field(members, "postal_code")
    country, country_src, _ = _pick_field(members, "country")
    bdate, bdate_src, bdate_conf = _pick_field(members, "birth_date")
    created_at, _, _ = _pick_field(members, "created_at_utc")

    populated_confs = [c for c in (first_conf, last_conf, email_conf, phone_conf, bdate_conf) if c > 0]
    record_conf = min(populated_confs) if populated_confs else 0.5

    full_name = " ".join(p for p in (first, last) if p) or full_norm

    return cid, {
        "customer_id": cid,
        "first_name": first, "first_name_source": first_src, "first_name_confidence": first_conf,
        "last_name": last, "last_name_source": last_src, "last_name_confidence": last_conf,
        "full_name": full_name, "full_name_source": full_src, "full_name_confidence": full_conf,
        "email_hash": hash_pii(email), "email_source": email_src, "email_confidence": email_conf,
        "phone_hash": hash_pii(phone), "phone_source": phone_src, "phone_confidence": phone_conf,
        "street_token": _street_token(street), "street_source": street_src, "street_confidence": street_conf,
        "city": city, "city_source": city_src,
        "region": region, "region_source": region_src,
        "postal_code": zip_, "postal_code_source": zip_src,
        "country": country, "country_source": country_src,
        "birth_date": bdate, "birth_date_source": bdate_src, "birth_date_confidence": bdate_conf,
        "record_confidence": record_conf,
        "n_sources": len({m["_source"] for m in members}),
        "created_at_utc": created_at,
    }


# --- Persistence ------------------------------------------------------------

_MASTER_COLUMNS = (
    "customer_id",
    "first_name", "first_name_source", "first_name_confidence",
    "last_name", "last_name_source", "last_name_confidence",
    "full_name", "full_name_source", "full_name_confidence",
    "email_hash", "email_source", "email_confidence",
    "phone_hash", "phone_source", "phone_confidence",
    "street_token", "street_source", "street_confidence",
    "city", "city_source",
    "region", "region_source",
    "postal_code", "postal_code_source",
    "country", "country_source",
    "birth_date", "birth_date_source", "birth_date_confidence",
    "record_confidence", "n_sources", "created_at_utc",
)


def _wipe_curated(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("DELETE FROM curated.customer_xref")
    con.execute("DELETE FROM curated.customer_master")
    con.execute("DELETE FROM curated.customer_review")


def _insert_master(con: duckdb.DuckDBPyConnection, masters: list[dict[str, Any]]) -> None:
    if not masters:
        return
    placeholders = ", ".join(["?"] * len(_MASTER_COLUMNS))
    cols = ", ".join(_MASTER_COLUMNS)
    rows = [tuple(m.get(c) for c in _MASTER_COLUMNS) for m in masters]
    con.executemany(
        f"INSERT INTO curated.customer_master ({cols}) VALUES ({placeholders})",
        rows,
    )


def _insert_xref(con: duckdb.DuckDBPyConnection, xrefs: list[tuple[str, str, str, str, float]]) -> None:
    if not xrefs:
        return
    con.executemany(
        "INSERT INTO curated.customer_xref (customer_id, _source, _source_id, match_method, match_score) "
        "VALUES (?, ?, ?, ?, ?)",
        xrefs,
    )


def _insert_reviews(con: duckdb.DuckDBPyConnection, reviews: list[dict[str, Any]]) -> int:
    rows: list[tuple[Any, ...]] = []
    now = utc_now()
    for rev in reviews:
        rid = str(uuid.uuid5(NS, "review:" + rev["left"] + "|" + rev["right"]))
        rows.append((
            rid, rev["left"], rev["right"], float(rev["score"]),
            json.dumps(rev["features"]), now,
        ))
    if rows:
        con.executemany(
            "INSERT INTO curated.customer_review (review_id, left_customer, right_customer, score, features, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
    return len(rows)


def run(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Run identity resolution end-to-end. Idempotent: wipes curated first."""
    _wipe_curated(con)
    records = _load_conformed(con)
    by_key: dict[str, dict[str, Any]] = {
        _key(r["_source"], r["_source_id"]): r for r in records
    }

    uf, pos_by_custid = _deterministic_pass(records)
    _apply_loyalty_fk(con, uf, pos_by_custid)

    reviews = _fuzzy_pass(records, uf)

    # Build groups and masters.
    groups = uf.groups()
    masters: list[dict[str, Any]] = []
    xrefs: list[tuple[str, str, str, str, float]] = []
    for _root, member_keys in groups.items():
        members = [by_key[k] for k in member_keys if k in by_key]
        if not members:
            continue
        cid, master = _build_master(members)
        masters.append(master)
        for m in members:
            method = "deterministic" if len(members) > 1 else "singleton"
            score = master["record_confidence"]
            xrefs.append((cid, m["_source"], m["_source_id"], method, score))

    _insert_master(con, masters)
    _insert_xref(con, xrefs)
    n_reviews = _insert_reviews(con, reviews)

    auto_merges = sum(1 for k in by_key if uf.find(k) != k)
    return {
        "masters": len(masters),
        "xrefs": len(xrefs),
        "reviews": n_reviews,
        "auto_merges": auto_merges,
    }
