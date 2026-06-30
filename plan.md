# Scenario 3 — Single Customer View — Team-Plan

**Team:** 6 Personen (A–F) · **Dauer:** 80 min · **Stack:** Python-Backend + React-Frontend

## Stack-Entscheidung

| Schicht | Technologie | Warum |
|---|---|---|
| Lakehouse / Storage | **DuckDB** (`warehouse/fabrikam.duckdb`) | Eine Datei, zero infra, SQL + Parquet, demo-fähig |
| Backend-Code | **Python 3.11**, Polars, rapidfuzz, phonenumbers | Schnell, lesbar, gute CSV-/JSON-Ingest-Story |
| API | **FastAPI** + uvicorn | Auto-OpenAPI, Pydantic-Validierung, läuft lokal |
| Frontend | **React 18 + Vite + TypeScript** | Schnelles HMR, kein Webpack-Theater |
| UI-Lib | **Tailwind CSS** + **shadcn/ui** | Pragmatisch, keine Lock-in, gut mit Claude generierbar |
| Daten-Fetching | **TanStack Query** | Caching, Re-fetch, optimistic updates für Stewardship |
| Charts | **Recharts** | Reicht für Quality-Dashboard |

**Repo-Layout**

```
backend/
  pipeline/           # ingest, conform, match, quality, schemas, normalize
  api/                # FastAPI app (Endpoints unten)
  tests/              # pytest + Matcher-Eval (Challenge 7)
frontend/
  src/
    pages/            # SwampDashboard, GoldenRecord, StewardshipQueue, LineageTrace
    components/
    api/              # generierter Client (openapi-typescript)
warehouse/            # DuckDB-Datei (gitignored)
decisions/            # ADRs
docs/                 # the-mess.md, catalog/
```

**Backend-API (Vertrag, frühe Fixierung in Phase 1)**

```
GET  /api/sources                    -> [{name, row_count, quality_score, last_ingested_at}]
GET  /api/customers?q=...            -> Paginierte Golden Records
GET  /api/customers/{id}             -> Master + xref (alle Quell-Rows) + field-confidence
GET  /api/customers/{id}/lineage     -> Pfad raw -> conformed -> curated
GET  /api/review-queue               -> Paare im Band 0.70–0.89
POST /api/review/{review_id}         -> {decision: "merge"|"keep_separate"}  -> aktualisiert curated
GET  /api/quality/checks             -> Letzter Quality-Run, pro Check
GET  /api/sources/{name}/profile     -> Completeness/Freshness/Anomalies (Challenge 9)
```

---

## Phase 1 — Fundament (0–15 min)

| Person | Aufgabe | Was zu tun ist |
|---|---|---|
| **A + B** | The Mess (Challenge 1, **Backend**) | Daten existieren bereits in `acq_*/`, `crm/`, `pos/`, `loyalty/`, `ecommerce/`. **Inspect-Half**: `docs/the-mess.md` schreiben — pro Quelle die realen Issues katalogisieren (Mojibake, Excel-Seriendaten, Dubletten, Encoding-Verlust). Cross-Source-Cases auflisten (Sean O'Brien × 4, Maria Hernandez × 4, Jürgen Müller × 2, David Lee × 3). |
| **C** | The Blueprint (Challenge 2) | `decisions/ADR-0001-blueprint.md`: 3-Zonen-Lakehouse (raw → conformed → curated), PII-Regeln, Retention, **plus** Sektion "What we deliberately chose not to do". 3-Level `CLAUDE.md` anlegen: Root, per-Zone (`warehouse/raw/`, `…/conformed/`, `…/curated/`), User-Level. |
| **D** | Projekt-Setup (**beide Stacks**) | `backend/`: `pyproject.toml` mit duckdb/polars/fastapi, `pipeline/`-Skelett, `api/main.py` mit Health-Check. `frontend/`: `npm create vite@latest -- --template react-ts`, Tailwind + shadcn/ui init, TanStack Query Provider, `.env` mit `VITE_API_URL=http://localhost:8000`. Beide unter `make dev` lauffähig. |
| **E + F** | Frontend-Wireframes + API-Vertrag | Auf Papier/Excalidraw: 4 Screens skizzieren (Swamp-Dashboard, Golden-Record, Stewardship-Queue, Lineage). **OpenAPI-Vertrag oben fixieren**, damit Backend und Frontend parallel laufen können. Mock-Server (z.B. `msw`) im Frontend einrichten, der die Endpoints stubt — so kann das Frontend bauen, bevor das Backend fertig ist. |

**Phase-1-Gate:** ADR ist gemerged, `make dev` startet Backend (Port 8000) und Frontend (Port 5173), Frontend zeigt Health-Check vom Backend.

---

## Phase 2 — Hauptarbeit (15–65 min)

| Person | Aufgabe | Was zu tun ist |
|---|---|---|
| **A** | The Intake (Challenge 3, **Backend**) | `backend/pipeline/ingest.py`: ein Loader pro Quelle (7 Stück), je mit Lineage-Spalten (`_source`, `_source_file`, `_source_row`, `_ingested_at`, `_raw_payload`). Rheinland: per-Row-Encoding-Detection. Sunset: Excel-Seriendaten. CRM: BOM + `"NULL"`-String. Idempotent (Truncate-and-Insert pro Lauf). |
| **B** | Conform-Layer + Validation-Retry (**Backend**) | `backend/pipeline/conform.py`: raw → `conformed.customer` mit kanonischem Schema. Pure Normalizer in `pipeline/normalize.py` (Email, E.164-Phone, Namen, Datums-Parser mit Excel-Serial-Erkennung, ZIP-Padding). Fehlerhafte Zeilen → `conformed._reject` mit `reject_reason` + `reject_field`. Validation-Retry-Loop für mehrdeutige Datumsformate (strict → dateutil → reject). |
| **C** | The Tripwire (Challenge 5, **Backend + Hooks**) | `backend/pipeline/quality.py`: Schema-Drift (BLOCK), Null-Explosion (ALERT), Volume-Anomalie (ALERT), Referenzielle Integrität `loyalty.pos_customer_id ↔ pos.cust_id` (ALERT). Pro Check dokumentiert: Block vs. Alert. **PreToolUse-Hook** `.claude/hooks/curated_gate.sh`, der `quality.assert_contracts_pass()` aufruft und Writes in `curated/` blockiert, wenn Contract rot. |
| **D** | The Customer (Challenge 4, **Backend**) + Catalog (Challenge 6) | `backend/pipeline/match.py`: 2-Pass (deterministisch via Email/Phone/FK, dann Fuzzy mit Blocking via `(last_initial, region, birth_year)` + rapidfuzz). Field-level Survivorship + Confidence. Thresholds: ≥0.90 auto-merge, 0.70–0.89 → `curated.customer_review`, <0.70 separat. **Catalog**: `docs/catalog/customer.md`, `…/source_*.md` (analyst-lesbar, mit Link auf Upstream-Contract). |
| **E** | Frontend: Swamp-Dashboard + Golden-Record-Viewer | `pages/SwampDashboard.tsx`: pro Quelle Karten mit Row-Count, Completeness, Anomaly-Count, letzter Ingest. Recharts-Balken pro Quality-Check. `pages/GoldenRecord.tsx`: Suche → Detail. Zeigt Master-Row + alle Source-Rows (xref), pro Feld die Quelle und Confidence (Tooltip mit Begründung). |
| **F** | Frontend: Stewardship-Queue + Lineage | `pages/StewardshipQueue.tsx`: Tabelle der Pairs aus dem 0.70–0.89-Band, Side-by-side-Diff der zwei Records, Buttons "Merge" / "Keep separate" → `POST /api/review/{id}`. `pages/LineageTrace.tsx`: gegeben `customer_id`, zeigt graphisch (oder Tree) den Pfad: curated.master ← xref ← conformed.customer ← raw.{source} ← `_raw_payload`. |

**Phase-2-Gate (60 min):** `python -m pipeline.run` läuft End-to-End. Frontend zeigt echte Daten aus der API (kein Mock mehr). Mindestens 3 von 4 Screens funktionsfähig.

---

## Phase 3 — Abschluss (65–80 min)

| Person | Aufgabe | Was zu tun ist |
|---|---|---|
| **C** | The Scorecard (Challenge 7, **Backend**) | `backend/tests/golden_pairs.csv`: ≥20 gelabelte Paare, stratifiziert (easy / hard / boundary / negative). Headline-Cases: Sean O'Brien × 4, Maria Hernandez × 4, Jürgen Müller × 2, David Lee × 3 (inkl. boundary `+amazon`), Sean Williams ≠ Sean Rodriguez (negativ), Jurgen Schmidt Berlin ≠ Köln (negativ). `tests/test_matcher_eval.py`: Precision, Recall, **False-Confidence-Rate**. In CI (`pytest`). |
| **A + B** | Polish Backend + Catalog | Edge-Cases im Conform-Layer durchgehen (POS-Mojibake, Sunset-Phone-ist-ein-Datum), Reject-Reasons konsolidieren. Catalog-Einträge fertig. |
| **D** | API → Frontend Integration durchziehen | Sicherstellen, dass alle Endpoints liefern was die Pages brauchen. OpenAPI-Schema regenerieren, TypeScript-Client neu erzeugen (`openapi-typescript`). |
| **E + F** | Frontend-Polish + Demo-Story | Loading-States, Empty-States, kurze Anleitungs-Tooltips. **Demo-Reihenfolge**: (1) Swamp-Dashboard zeigt 7 chaotische Quellen, (2) Golden-Record für Maria Hernandez — alle 4 Quellen vereint mit Confidence, (3) Stewardship-Queue: David Lee `+amazon`-Boundary-Case → Reviewer entscheidet, (4) Hook-Block-Demo: kaputtes Contract → curated blockiert. |
| **Alle** | README + presentation.html | `README.md` nach Template (Participants, Challenges-Status, How-to-Run). Claude generiert `presentation.html` aus README + ADR + Demo-Screenshots. |

**Phase-3-Gate (80 min):** Demo läuft in der gewählten Reihenfolge ohne Eingreifen. CI ist grün. README + presentation.html committed.

---

## Risiken & Plan B

- **Frontend hängt am Backend.** → Mock-Server (`msw`) ab Phase 1 garantiert, dass das Frontend immer baut. Notfalls Demo komplett gegen Mock.
- **Matcher zu schlecht für Demo.** → Threshold senken auf 0.85, mehr Auto-Merges. Eval-Zahlen ehrlich auf der Slide.
- **CORS-Probleme zwischen `:5173` und `:8000`.** → FastAPI `CORSMiddleware` in `api/main.py` direkt in Phase 1 setzen, nicht später debuggen.
- **Zeit knapp.** Prioritäten: Backend-Pipeline + Golden-Record-Viewer + Hook-Block-Demo > Stewardship-Queue > Lineage-Trace.

## Challenges-Abdeckung

| # | Challenge | Wer | Wo |
|---|---|---|---|
| 1 | The Mess | A+B | `docs/the-mess.md` (inspection-half der existierenden Daten) |
| 2 | The Blueprint | C | `decisions/ADR-0001-blueprint.md`, 3-Level `CLAUDE.md` |
| 3 | The Intake | A, B | `backend/pipeline/ingest.py`, `conform.py` |
| 4 | The Customer | D | `backend/pipeline/match.py` |
| 5 | The Tripwire | C | `backend/pipeline/quality.py` + `.claude/hooks/` |
| 6 | The Catalog | D | `docs/catalog/*.md` |
| 7 | The Scorecard | C | `backend/tests/golden_pairs.csv`, `test_matcher_eval.py` |
| 8 | The Trace *(stretch)* | F | `pages/LineageTrace.tsx` + `/api/customers/{id}/lineage` |
| 9 | The Swarm *(stretch)* | — | Skip, wenn Zeit knapp; sonst Source-Profiling als Task-Subagents. |
