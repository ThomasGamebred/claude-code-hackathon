# ADR-0005 — Deterministic guardrails in code, probabilistic judgement isolated and eval-gated

**Status:** Accepted · **Date:** 2026-06-30

## Context
The pipeline mixes two kinds of decision: exact rules ("curated rows must have a unique
golden_id") and fuzzy judgement ("are these two records the same person?"). Conflating
them is how data platforms rot — a guardrail that fires "usually" isn't a guardrail, and
a fuzzy call frozen into rigid code can't improve.

## Decision
Split them, hard, along the determinism line:

| Decision type | Where it lives | Enforcement |
|---|---|---|
| Schema contracts, null/range/uniqueness, referential integrity | `pipeline/dq.py` + `contracts.py` (code) | `PreToolUse` hook **blocks**; pipeline gate **aborts** |
| Curated-zone write safety | `hooks/curated_guard.py` (deterministic hook) | blocks the write |
| Entity-match judgement | `resolve.score_pair` + `matcher_prompt.md` | **eval-gated** (`make eval`), thresholds, review queue |
| Zone preferences (PII handling, "prefer recent") | per-zone `CLAUDE.md` (prompt) | guidance |

Concretely:
- **`PreToolUse` hook** blocks writes into the curated zone until the schema contract
  passes. Deterministic, non-negotiable. (Block = refuse corruption.)
- **`PostToolUse`** is the place for PII redaction into logs/exports. (Redact = transform.)
- **Prompts / per-zone `CLAUDE.md`** carry the probabilistic preferences ("prefer the
  most recent address", "treat raw as most sensitive").
- The matcher is the one probabilistic engine, and it is **isolated** in a single scored
  function and **gated by an eval** with precision / recall / false-confidence thresholds.

## Why (the distinction the cert keeps testing)
Hooks are for things that must be *true*; prompts are for things we *prefer*. A range
check is a hook because "match_confidence in [0,1]" is not a preference. "Prefer the
freshest address" is a prompt because it's a judgement that can be overridden.

## What we deliberately chose NOT to do
- **No prompt-based data-quality checks.** Probabilistic guardrails give probabilistic
  safety. DQ is code.
- **No hard-coded match rules without an eval.** Any rule change must move a number in
  the scorecard, or it doesn't ship.
- **No silent auto-merge of the uncertain.** Pairs in `[0.72, 0.90)` go to a review
  queue, not into curated.
