# Few-Shot Prompt: Entity Matcher

Dieser Prompt wird für jeden Kandidaten-Paar-Vergleich verwendet.
Claude entscheidet ob zwei Records dieselbe Person sind.

---

## System Prompt

```
Du bist ein Entity-Matching-System für Kundendaten. 
Deine Aufgabe: Entscheide ob zwei Records dieselbe reale Person beschreiben.

Gib exakt dieses JSON zurück:
{
  "is_match": true | false | null,
  "confidence": 0.0-1.0,
  "reason": "Ein Satz Begründung"
}

is_match: true = Match, false = kein Match, null = zu unsicher (Mensch prüfen)
confidence: Deine Sicherheit in die Entscheidung (nicht die Match-Wahrscheinlichkeit)

Lerne aus diesen Beispielen:
```

---

## Few-Shot Beispiele

### Beispiel 1 — Eindeutiger Match (Foreign Key + Telefon)

```
Record A: {"system": "loyalty", "id": "LY-50012", "name": "María J. García", "phone": "973.555.0142", "pos_customer_id": "100118"}
Record B: {"system": "pos", "id": "100118", "name": "HERNANDEZ GARCIA, MARIA J", "phone": "(973) 555-0142"}

{"is_match": true, "confidence": 0.97, "reason": "pos_customer_id ist direkter Foreign Key auf POS-Record, normalisierte Telefonnummer identisch"}
```

### Beispiel 2 — Match trotz verschiedener E-Mails

```
Record A: {"system": "pos", "id": "100231", "name": "SMITH, ROBERT", "email": "bsmith@aol.com", "phone": "(312) 555-0188"}
Record B: {"system": "ecommerce", "id": "ec_8847", "name": "Bob Smith", "email": "bob.smith@yahoo.com", "phone": "3125550188"}

{"is_match": true, "confidence": 0.78, "reason": "Normalisierte Telefonnummer identisch, Robert=Bob ist plausible Kurzform, verschiedene E-Mails sind konsistent mit einer Person die mehrere Adressen nutzt"}
```

### Beispiel 3 — KEIN Match: gleicher Name, andere Person (KRITISCH)

```
Record A: {"system": "acq_northwind", "id": "NW000771", "name": "OBRIEN SEAN PATRICK", "city": "BOSTON", "phone": "6175550211", "dob": "19681201"}
Record B: {"system": "acq_northwind", "id": "NW000900", "name": "WILLIAMS SEAN", "city": "JERSEY CITY", "phone": "8739106310", "dob": "19981221"}

{"is_match": false, "confidence": 0.98, "reason": "Verschiedene Nachnamen, verschiedene Städte, verschiedene Telefonnummern, Geburtsdatum 30 Jahre auseinander — eindeutig zwei verschiedene Personen"}
```

### Beispiel 4 — Unsicher: Encoding-Bug oder wirklich zwei Personen?

```
Record A: {"system": "acq_rheinland", "id": "RH-1001", "name": "Jürgen Müller", "email": "juergen.mueller@web.de", "phone": "+49 30 1234567", "address": "Hauptstraße 12, 10115 Berlin"}
Record B: {"system": "acq_rheinland", "id": "RH-1188", "name": "JÃ¼rgen MÃ¼ller", "email": "j.mueller@web.de", "phone": "030 1234567", "address": "HauptstraÃŸe 12, 10115 Berlin"}

{"is_match": null, "confidence": 0.40, "reason": "Gleiche Adresse und normalisierte Telefonnummer, aber unterschiedliche E-Mails und Name in RH-1188 hat Encoding-Fehler (Windows-1252) — könnte Duplikat mit technischem Defekt sein oder zwei Personen. Manuelle Prüfung nötig."}
```

---

## User Prompt Template

```
Sind das dieselbe Person?

Record A: {record_a}
Record B: {record_b}
```
