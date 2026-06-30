# Meine Rolle: Entity Resolver (E/F)

Szenario 3 — "Der Sumpf" — Fabrikam Retail
Ich baue den Entity Matcher und den Golden Record.

---

## Daten sind schon da — ich kann sofort loslegen

`data/raw/` hat 7 echte Quellsysteme mit realem Dreck:
- `pos/pos_export_2023-11.csv` — Duplikat CUST_ID 100231 (Robert Smith, zweimal!)
- `crm/crm_contacts.csv` — BOM, inkonsistente Datumsformate
- `ecommerce/customers.json` — JSON, sauberste Quelle
- `loyalty/loyalty_members.csv` — hat `pos_customer_id` Spalte (direkter FK zu POS!)
- `acq_rheinland/kunden.csv` — Semikolon-getrennt, Windows-Encoding kaputt (JÃ¼rgen statt Jürgen)
- `acq_northwind/legacy_customers.txt` — Pipe-getrennt, all caps, truncated names
- `acq_sunset/catalog_customers.csv` — Excel-Serial-Datumswerte (44197 statt 2021-01-01)

### Wichtigste Erkenntnisse aus den Daten

**Goldener Trick:** Loyalty hat `pos_customer_id` — das ist ein eingebauter Foreign Key.
Für alle Loyalty-Einträge mit gesetztem `pos_customer_id` ist der POS-Match schon bekannt.
Das vereinfacht das Blocking massiv.

**Telefon ist der zuverlässigste Match-Key** (konsistenter als E-Mail):
- Maria Hernandez: POS `(973) 555-0142` = Loyalty `973.555.0142` = ECommerce `+1-973-555-0142`

**Bekannte Multi-System-Personen (aus Datensicht bereits erkennbar):**
- Maria Hernandez/García: POS 100118 + CRM + Loyalty LY-50012 + ECommerce ec_8841
- Robert/Bob Smith: POS 100231 (Duplikat!) + Loyalty LY-50019 + ECommerce ec_8847
- Sean O'Brien: POS 100244 + CRM + NW000771 + SC1007 (4 Systeme, 4 E-Mails!)
- Jürgen Müller: Loyalty LY-50044 + RH-1001 + RH-1188 (RH-1188 = Encoding-Bug-Duplikat von RH-1001)

**Bester Negativ-Fall für Few-Shot:** Jürgen Müller RH-1001 vs RH-1188 — gleicher Name,
gleiche Adresse, aber `juergen.mueller@web.de` vs `j.mueller@web.de` und Encoding kaputt.
Ist das dieselbe Person (Duplikat) oder zwei verschiedene? → Genau dieser Fall muss im Prompt.

---

## Was ich tue — nach Phase

### Phase 1 (0–15 Min) — NUR Design, noch kein Code

Starte Claude Code mit diesem Prompt:

```
Wir bauen einen Entity Matcher für Fabrikam Retail (Hackathon, Szenario "Der Sumpf").
Die Rohdaten liegen bereits in data/raw/ mit 7 Quellsystemen.

Lies zuerst die folgenden Dateien um die Daten zu verstehen:
- data/raw/pos/pos_export_2023-11.csv (erste 10 Zeilen)
- data/raw/loyalty/loyalty_members.csv (erste 10 Zeilen) — hat pos_customer_id FK!
- data/raw/acq_rheinland/kunden.csv (erste 10 Zeilen) — Encoding kaputt

Deine Aufgabe jetzt (nur Design, noch kein Code):

1. Erstelle decisions/ADR-003-entity-matching.md mit:
   - Blocking-Strategie: pos_customer_id in Loyalty als direkten FK nutzen (spart viele Vergleiche)
   - Danach: Telefonnummer als primären Match-Key (konsistentestes Feld across systems)
   - Fallback: Name + PLZ/Stadt
   - Survivorship-Regeln: bei Feldkonflikt welche Quelle gewinnt?
   - "Was wir bewusst NICHT tun"-Abschnitt

2. Erstelle pipelines/matcher_prompt.md — Few-Shot Prompt mit 4 echten Beispielen aus den Daten:

   MATCH (eindeutig, via FK):
   Record A: {system: "loyalty", id: "LY-50012", name: "María J. García", phone: "973.555.0142", pos_customer_id: "100118"}
   Record B: {system: "pos", id: "100118", name: "HERNANDEZ GARCIA, MARIA J", phone: "(973) 555-0142"}
   → MATCH, Confidence: 0.97, Reason: "pos_customer_id direkter FK + normalisierte Telefon identisch"

   MATCH (via Telefon, verschiedene E-Mails):
   Record A: {system: "pos", id: "100231", name: "SMITH, ROBERT", email: "bsmith@aol.com", phone: "(312) 555-0188"}
   Record B: {system: "ecommerce", id: "ec_8847", name: "Bob Smith", email: "bob.smith@yahoo.com", phone: "3125550188"}
   → MATCH, Confidence: 0.78, Reason: "Normalisierte Telefon identisch, Name (Robert=Bob) plausibel, verschiedene E-Mails aber konsistent mit einer Person"

   KEIN MATCH (kritischer Negativ-Fall — Encoding-Duplikat vs echter Unterschied):
   Record A: {system: "acq_rheinland", id: "RH-1001", name: "Jürgen Müller", email: "juergen.mueller@web.de", phone: "+49 30 1234567"}
   Record B: {system: "acq_rheinland", id: "RH-1188", name: "JÃ¼rgen MÃ¼ller", email: "j.mueller@web.de", phone: "030 1234567"}
   → UNSICHER, Confidence: 0.40, Reason: "Gleiche Adresse + normalisierte Telefon identisch, aber verschiedene E-Mails — könnte Duplikat mit Encoding-Bug sein ODER zwei verschiedene Personen. Mensch prüfen."

   ESKALIERUNG (4 Systeme, 4 verschiedene E-Mails):
   Record A: {system: "pos", id: "100244", name: "O'BRIEN, SEAN", phone: "(617) 555-0211"}
   Record B: {system: "crm", id: "0035000ghi", name: "Obrien, Sean", email: "sean.obrien@acme.example", phone: "6175550211"}
   → MATCH, Confidence: 0.85, Reason: "Normalisierte Telefon identisch, Name-Variante plausibel (Apostroph fehlt)"
```

---

### Phase 2 (15–65 Min) — Implementierung

Warte auf:
- `data/conformed/` hat Daten (von A+B + C)
- `decisions/ADR-002-schema.md` existiert (von D/C)

Dann starte Claude Code mit:

```
Implementiere jetzt den Entity Matcher auf Basis von decisions/ADR-003-entity-matching.md.

1. pipelines/entity_matcher.py
   - Input: alle DataFrames aus data/conformed/
   - Blocking-Schritt: Kandidatenpaare reduzieren (gleicher Anfangsbuchstabe Nachname)
   - Scoring: Few-Shot Prompt aus pipelines/matcher_prompt.md nutzen
   - Output: Cluster-Entscheidungen mit Confidence Score

2. pipelines/golden_record_builder.py
   - Survivorship-Regeln aus ADR-003 anwenden
   - Output: data/curated/golden_records.parquet
   - Format aus decisions/ADR-002-schema.md:
     {customer_id, full_name, email, phone, address,
      source_ids[], confidence_score, match_reason, schema_version}

Wichtig: confidence_score 0.0 ist ein valides Ergebnis (kein Match gefunden).
```

---

### Phase 3 (65–80 Min) — Scorecard (wer Kapazität hat)

Einer von E/F macht The Scorecard. Starte Claude Code mit:

```
Baue den Eval-Harness für den Entity Matcher.

1. evals/labeled_dataset.json — mind. 20 Paare, stratifiziert:
   - EINDEUTIGER_MATCH (≥ 3 Paare, gleiche E-Mail, confidence soll ≥ 0.85)
   - WAHRSCHEINLICHER_MATCH (≥ 3 Paare, Name + Stadt, confidence 0.5–0.84)
   - KEIN_MATCH_ÄHNLICHE_NAMEN (≥ 4 Paare — das ist der härteste Fall)
   - ESKALIERUNG_NÖTIG (≥ 2 Paare)
   Nutze evals/ground_truth_matches.json als Basis (von Person A/B erstellt).

2. evals/run_scorecard.py — berechnet:
   - Precision, Recall, False Confidence Rate
   - Aufgeschlüsselt nach Kategorie (nicht nur Gesamt!)
   - Schreibt evals/latest_report.md
   - --fail-threshold 0.7 → Exit Code 1 für CI

False Confidence Rate ist die wichtigste Metrik: confident-and-wrong ist das Schlimmste.
```

---

## Mein wichtigster Beitrag

Die **Negativ-Beispiele** im Few-Shot Prompt (`matcher_prompt.md`).
Zwei scharfe "KEIN MATCH"-Fälle entscheiden ob der Matcher die Jury überzeugt.

## Abhängigkeiten

| Was ich brauche | Von wem | Wann | Status |
|---|---|---|---|
| Ordnerstruktur + ADR-002 | D (Architekt) | Phase 1 Ende | ausstehend |
| `data/conformed/` Daten | C (Ingestion) | Phase 2 Start | ausstehend |
| `evals/ground_truth_matches.json` | A+B | Phase 3 | **Rohdaten schon da, können direkt daraus gebaut werden** |

## Was sich durch die vorhandenen Daten ändert

- **Phase 1** kann ich sofort starten — Daten existieren, ich muss nicht warten
- **Few-Shot Prompt** mit echten Beispielen aus den Dateien — viel überzeugender als Phantasiedaten
- **Ground Truth** kann ich selbst aus den Daten ableiten (pos_customer_id ist schon ein Label!)
- **Blocking-Strategie** ist durch den pos_customer_id FK bereits halb gelöst
