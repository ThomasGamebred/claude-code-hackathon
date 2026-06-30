# ADR-004: Guardrail-Schichtung — Hook vs. Prompt

**Status:** Accepted  
**Datum:** 2026-06-30

---

## Kontext

`data/curated/` enthält die Golden Records — das einzige Artefakt das downstream von
Analysten und Berichten konsumiert wird. Ein direktes Schreiben ohne vorherige
Qualitätsprüfung würde stille Datenfehler in die Produktion bringen.

Zwei Mechanismen stehen zur Verfügung: PreToolUse Hooks und CLAUDE.md-Regeln.

---

## Entscheidung

**Hook** für `data/curated/` Schreibschutz — **CLAUDE.md-Regel** für Zonenhinweise.

### Warum Hook für den harten Stopp

Ein Hook ist **deterministisch**: Er prüft den Tool-Call mechanisch und gibt `block` zurück.
Claude kann einen Hook nicht durch Argumentation umgehen, auch nicht wenn der Nutzer
es darum bittet oder der Kontext überzeugend klingt.

Eine CLAUDE.md-Regel ist **probabilistisch**: Claude liest sie als Präferenz.
Bei hinreichend überzeugender Begründung ("ich muss jetzt direkt schreiben weil...")
kann Claude sie ignorieren. Für eine Sicherheitsregel ist das nicht akzeptabel.

### Warum CLAUDE.md-Regel für die Zonen-Hinweise

`data/raw/CLAUDE.md` und `data/curated/CLAUDE.md` enthalten Kontext-Hinweise
("Was ist diese Zone, wofür ist sie da") — das sind Präferenzen und Erklärungen,
keine Sicherheitsregeln. Dafür ist ein Hook überdimensioniert.

---

## Schichtung im Überblick

| Mechanismus | Typ | Verwendet für |
|---|---|---|
| `PreToolUse` Hook | Deterministisch, hard stop | Schreibschutz `data/curated/` |
| `data/curated/CLAUDE.md` | Probabilistisch, Kontext | Erklärung warum curated besonders ist |
| `data/raw/CLAUDE.md` | Probabilistisch, Kontext | Erinnerung: raw ist read-only |

---

## Konsequenzen

- Jeder Schreibversuch auf `data/curated/` durch Claude wird blockiert — auch wenn der Nutzer es explizit anweist
- Einziger erlaubter Weg: `pipelines/golden_record_builder.py` (wird im Hook explizit erlaubt)
- Neue legitime Schreibpfade müssen im Hook-Code eingetragen werden
