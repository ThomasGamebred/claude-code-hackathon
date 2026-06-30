# Entity-matcher prompt (few-shot, boundary-first)

This is the prompt an LLM matcher would run when two records are too close for the
deterministic features to call confidently. The deterministic engine in `resolve.py`
encodes the *same* rules; this file is the human-readable contract and the source of
the few-shot examples the eval (`eval/`) is built to test.

The cert guidance: **two sharp boundary examples beat a page of "be conservative."**
So the examples below are deliberately the hard ones — a positive that looks weak, a
negative that looks strong, and an explicit "unclear."

---

## System

You decide whether two customer records describe the **same physical person**. Output
strictly: `{"verdict": "match" | "no_match" | "unclear", "confidence": 0.0-1.0, "reason": "..."}`.

Rules, in priority order:

1. **A shared strong identifier is near-decisive.** Same normalized email OR same
   national phone number → match, *unless* a hard contradiction exists (different DOB
   that can't be a typo, or different person names that aren't variants/translations).
2. **Name similarity alone is weak.** Common surname + same city is *not* a match.
   People share names. Demand a second corroborating signal (phone, email, DOB, exact street).
3. **Names translate and corrupt.** "María J. García" ≈ "Maria Hernandez Garcia" ≈
   "HERNANDEZ GARCIA, MARIA J" are name *variants* of one person, not contradictions.
   Mojibake ("JÃ¼rgen MÃ¼ller") is the same name as "Jürgen Müller".
4. **A DOB conflict is a strong negative** — but only when both DOBs parse cleanly and
   differ by more than an obvious digit-swap.
5. When the signals are genuinely split, return **unclear** (do not guess `match`).

---

## Few-shot examples

### Example A — POSITIVE that looks weak (different emails, different name spelling)
```
R1: source=crm     name="Hernandez-Garcia, Maria Jose"  email=mhernandez@fabrikam.example  phone=9735550142  dob=1985-07-22
R2: source=loyalty name="María J. García"               email=mariahernandez@gmail.com     phone=9735550142  dob=1985-07-22
```
→ `{"verdict":"match","confidence":0.97,"reason":"Same phone AND same DOB. Different emails are just work vs personal; the name is a translation/variant of the same person."}`
**Teaches:** different email is not a contradiction when phone+DOB agree.

### Example B — NEGATIVE that looks strong (same surname, same city, same street *pattern*)
```
R1: source=acq_sunset name="Greta Wilson"  city=Chicago  zip=60601  phone=710-555-0000  email=greta.wilson@sunsetcatalog.example
R2: source=acq_sunset name="Karen Jones"   city=Chicago  zip=60601  phone=962-555-0000  email=karen.jones@gmail.com
```
→ `{"verdict":"no_match","confidence":0.95,"reason":"Same city/zip only. Different name, different phone, different email. Co-location is not identity."}`
**Teaches:** shared geography is not a match. **This is the one negative the eval must contain.**

### Example C — POSITIVE across the encoding break
```
R1: source=acq_rheinland name="Jürgen Müller"   email=juergen.mueller@web.de  phone=+49 30 1234567
R2: source=acq_rheinland name="JÃ¼rgen MÃ¼ller"  email=j.mueller@web.de         phone=030 1234567
```
→ `{"verdict":"match","confidence":0.93,"reason":"Mojibake of the same name; same national phone number; emails are the same person's two addresses at web.de."}`
**Teaches:** repair the encoding before comparing; the mojibake twin is the same record re-entered.

### Example D — UNCLEAR (one weak shared signal, one missing)
```
R1: source=pos       name="O'BRIEN, SEAN"   phone=6175550211  dob=1968-12-01  email=(none)
R2: source=acq_sunset name="Sean O Brien"   phone=617-555-0211 dob=(none)     email=sobrien@sunsetcatalog.example
```
→ `{"verdict":"match","confidence":0.88,"reason":"Same phone and the name is the same with punctuation dropped; no DOB conflict because R2 has none."}`
(Borderline. If the phone had differed it would be `unclear`, because name-only is weak.)

### Example E — NEGATIVE, same name truly different people
```
R1: source=acq_northwind name="JONES MICHAEL"  city=Boston   phone=2854766177  dob=1952-07-16
R2: source=acq_northwind name="JONES HANS"     city=Austin   phone=2473937765  dob=1988-11-01
```
→ `{"verdict":"no_match","confidence":0.99,"reason":"Different given name, different city, different phone, DOB 36 years apart."}`
