# Fabrikam Retail — "Der Sumpf"

Hackathon Szenario 3: Data Engineering. Ziel ist ein Golden Record pro Kunde aus 7 Quellsystemen.

## Projekt

- **Repo:** ThomasGamebred/claude-code-hackathon, Branch `entity-resolver`
- **Stack:** Python, wird in `decisions/ADR-001-stack.md` festgelegt (noch ausstehend vom Architekten)
- **Meine Rolle:** Entity Resolver — Matcher + Golden Record Builder

## Ordnerstruktur

```
data/raw/          # Unveränderlich. Niemals bearbeiten, nur lesen.
data/conformed/    # Normalisierte Daten. Output der Ingestion-Pipeline.
data/curated/      # Golden Records. Nur via pipelines/golden_record_builder.py schreiben.
decisions/         # ADRs
pipelines/         # Python-Code
evals/             # Eval-Harness und labeled datasets
catalog/           # Datenkatalog für Analysten
```

## Quellsysteme

| Ordner | Format | Bekannte Probleme |
|---|---|---|
| `data/raw/pos/` | CSV | Duplikat CUST_ID 100231, all caps Namen |
| `data/raw/crm/` | CSV | BOM-Zeichen, inkonsistente Datumsformate |
| `data/raw/ecommerce/` | JSON | Sauberste Quelle |
| `data/raw/loyalty/` | CSV | Hat `pos_customer_id` FK — direkter Link zu POS |
| `data/raw/acq_rheinland/` | CSV (Semikolon) | Windows-1252 Encoding kaputt |
| `data/raw/acq_northwind/` | TXT (Pipe) | All caps, truncated names |
| `data/raw/acq_sunset/` | CSV | Excel-Serial-Datumswerte |

## Matching-Strategie (ADR-003)

1. `pos_customer_id` in Loyalty → direkter FK, Confidence 1.0, kein LLM nötig
2. Normalisierte Telefonnummer → primärer Match-Key
3. Name + PLZ → Fallback

Few-Shot Prompt: `pipelines/matcher_prompt.md`

## Regeln

- `data/raw/` niemals schreiben oder verändern
- `data/curated/` nur via `pipelines/golden_record_builder.py` — nicht direkt
- Telefonnummern immer normalisieren bevor verglichen wird (nur Ziffern + Ländercode)
- Confidence 0.0 ist ein valides Ergebnis (kein Match = Single-Source Record)
- Bei Confidence < 0.5 → `is_match: null`, nicht entscheiden

## Schlüssel-Dateien

- `decisions/ADR-003-entity-matching.md` — Matching-Strategie
- `pipelines/matcher_prompt.md` — Few-Shot Prompt mit echten Beispielen
- `PERSON_F.md` — meine Rolle und Phase-Prompts
