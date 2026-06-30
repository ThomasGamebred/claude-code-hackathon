# ADR-003: Entity Matching Strategy

**Status:** Accepted  
**Datum:** 2026-06-30  
**Autor:** Person E/F (Entity Resolver)

---

## Kontext

Fabrikam Retail hat 7 Quellsysteme. Dieselbe Person existiert unter verschiedenen IDs,
Schreibweisen und Formaten. Ziel ist ein Golden Record pro Person mit Confidence Score.

Herausforderungen aus den Rohdaten:
- Verschiedene Telefon-Formate für dieselbe Nummer: `(973) 555-0142` = `973.555.0142` = `+1-973-555-0142`
- Namen inkonsistent: `HERNANDEZ GARCIA, MARIA J` = `María J. García` = `Maria Hernandez`
- E-Mails divergieren pro System (Bob Smith hat `bsmith@aol.com` in POS, `bob.smith@yahoo.com` in ECommerce)
- Encoding-Fehler in acq_rheinland: `JÃ¼rgen MÃ¼ller` statt `Jürgen Müller`
- `loyalty_members.csv` hat `pos_customer_id` — direkter Foreign Key zu POS

---

## Entscheidung

### Matching-Pipeline: 3 Stufen

**Stufe 1 — Direkte Links (deterministisch, kein LLM)**  
Nutze `pos_customer_id` in Loyalty als eingebauten FK.  
Alle Loyalty-Einträge mit gesetztem `pos_customer_id` → direkt mit POS-Record verknüpft, Confidence: 1.0.  
Kein LLM-Aufruf nötig.

**Stufe 2 — Telefon-Blocking + Scoring (primärer Match-Key)**  
Telefonnummer normalisieren → nur Ziffern, immer mit Ländercode.  
Gleiche normalisierte Telefonnummer = Kandidatenpaar → Claude bewertet.  
Telefon ist der zuverlässigste Key: konsistenter als E-Mail (Personen haben mehrere Mails),
robuster als Name (Tipp- und Encoding-Fehler).

**Stufe 3 — Name + PLZ Fallback**  
Für Records ohne Telefon: normalisierter Nachname + PLZ als Blocking-Key.  
Claude bewertet Kandidatenpaare mit Few-Shot Prompt.

### Survivorship-Regeln

Bei Feldkonflikt zwischen gematchten Records gilt:

| Feld | Gewinnt |
|---|---|
| `email` | Neuester Timestamp (aktuellste Quelle) |
| `full_name` | CRM bevorzugt (manuell gepflegt), sonst ECommerce |
| `phone` | Häufigste normalisierte Nummer across sources |
| `address` | CRM bevorzugt, sonst ECommerce |
| `date_of_birth` | Älteste Quelle (am wenigsten geändert) |

### Confidence Score

- `1.0` — Direkter FK (pos_customer_id)
- `0.85–0.99` — Telefon + Name stimmen überein
- `0.50–0.84` — Telefon oder Name + Stadt, kein Widerspruch
- `0.20–0.49` — Unsicher, Widersprüche vorhanden → Eskalierung
- `0.0` — Kein Match gefunden (Single-Source Record)

---

## Was wir bewusst NICHT tun

- **Kein ML-Modell** — zu aufwendig für Hackathon, kein gelabeltes Trainingsdaten-Set
- **Kein Embedding-Matching** — Latenz und Kosten nicht rechtfertigbar
- **Keine transitive Closure** — wenn A=B und B=C dann A=C wird nicht automatisch durchgeführt
  (zu riskant ohne manuelle Prüfung)
- **Keine automatische Zusammenführung bei Confidence < 0.5** — immer Eskalierung

---

## Konsequenzen

- Telefonnormalisierung ist kritischer Schritt — Fehler hier propagieren in alle Matches
- Records ohne Telefon UND ohne `pos_customer_id` können nur über Name+PLZ gematcht werden — niedrigere Precision zu erwarten
- Encoding-Fehler in acq_rheinland müssen VOR dem Matching korrigiert werden
