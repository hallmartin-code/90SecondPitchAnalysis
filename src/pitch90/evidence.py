"""Evidence storage and validation.

The language model proposes facts with citations; this module checks them against
the extracted deck instead of trusting them: cited pages must exist, excerpts must
appear on those pages, calculated values must match their formulas, and facts that
share a key but disagree are marked as conflicting rather than silently resolved.
"""

from __future__ import annotations

import ast
import operator
import re
import unicodedata

from pitch90.models import (
    NOT_PROVIDED,
    CitationCheck,
    EvidenceStatus,
    ExtractedDeck,
    Fact,
    Inconsistency,
    LLMFact,
    Origin,
)

_MISSING_VALUES = {"", "not provided", "n/a", "none", "unknown", "not stated"}

# ------------------------------------------------------------------ text normalisation


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = re.sub(r"[‘’‚′]", "'", text)
    text = re.sub(r"[“”„″]", '"', text)
    text = re.sub(r"[‐-―−]", "-", text)
    text = re.sub(r"[^a-z0-9$%€£.,'\-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def excerpt_found(excerpt: str, haystack: str) -> bool:
    """True when every part of the excerpt (split on ellipses) occurs in the text."""
    hay = normalize(haystack)
    parts = [normalize(p) for p in re.split(r"\.\.\.|…|\[\.\.\.\]", excerpt)]
    parts = [p.strip(" .,") for p in parts if len(p.strip(" .,")) >= 3]
    return bool(parts) and all(p in hay for p in parts)


# ------------------------------------------------------------------ numbers

_SCALE = {
    "k": 1e3, "thousand": 1e3,
    "m": 1e6, "mm": 1e6, "mn": 1e6, "million": 1e6,
    "b": 1e9, "bn": 1e9, "billion": 1e9,
    "t": 1e12, "trillion": 1e12,
}
_NUMBER_RE = re.compile(
    r"(?P<cur>[$€£¥])?\s?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"\s?(?P<suffix>%|x\b|k\b|thousand\b|mm\b|mn\b|m\b|million\b|bn\b|b\b|billion\b|t\b|trillion\b)?",
    re.IGNORECASE,
)


def number_candidates(match: re.Match) -> set[float]:
    raw = float(match.group("num").replace(",", ""))
    suffix = (match.group("suffix") or "").lower()
    values = {raw}
    if suffix in _SCALE:
        values.add(raw * _SCALE[suffix])
    return values


def numbers_in(text: str) -> list[tuple[str, set[float]]]:
    return [(m.group(0).strip(), number_candidates(m)) for m in _NUMBER_RE.finditer(text or "")]


def parse_value(value: str) -> float | None:
    """Best-effort numeric value of a fact value (largest scaled candidate)."""
    found = numbers_in(value)
    if not found:
        return None
    return max(found[0][1])


def _close(a: float, b: float, rel: float = 0.005) -> bool:
    return abs(a - b) <= max(abs(a), abs(b)) * rel + 1e-9


# ------------------------------------------------------------------ formula checks

_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg,
}


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        if isinstance(node.op, ast.Pow):
            raise ValueError("powers not allowed")
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("unsupported expression")


def evaluate_formula(formula: str) -> float | None:
    """Evaluate the left-hand side of 'expr = result' (or the whole string).

    Only numbers and + - * / ( ) are allowed; currency symbols, thousands
    separators and percent signs are stripped. Returns None if not evaluable.
    """
    expr = formula.split("=")[0]
    expr = re.sub(r"(\d),(?=\d{3})", r"\1", expr)
    expr = expr.replace("×", "*").replace("÷", "/").replace("$", "").replace("%", "")
    expr = re.sub(r"(?<=\d)\s*[xX]\s*(?=\d)", "*", expr)
    if not re.fullmatch(r"[\d\s.+\-*/()]+", expr.strip() or "x"):
        return None
    try:
        return _eval(ast.parse(expr.strip(), mode="eval").body)
    except (SyntaxError, ValueError, ZeroDivisionError):
        return None


# ------------------------------------------------------------------ fact pipeline


def is_missing_value(value: str | None) -> bool:
    return (value or "").strip().lower() in _MISSING_VALUES


def build_facts(llm_facts: list[LLMFact], deck: ExtractedDeck) -> list[Fact]:
    valid_pages = deck.unit_numbers
    label = deck.unit_label
    facts: list[Fact] = []
    for i, lf in enumerate(llm_facts, start=1):
        fact = Fact(**lf.model_dump(), id=f"F{i:02d}")
        bad = sorted(set(fact.source_pages) - valid_pages)
        if bad:
            fact.flags.append(f"Removed citation to non-existent {label}(s) {bad}.")
        fact.source_pages = sorted(set(fact.source_pages) & valid_pages)

        if fact.status == EvidenceStatus.MISSING or is_missing_value(fact.value):
            fact.status = EvidenceStatus.MISSING
            fact.value = NOT_PROVIDED
            fact.source_pages, fact.excerpt = [], None
            fact.citation_check = CitationCheck.NO_CITATION
            facts.append(fact)
            continue

        if not fact.source_pages:
            fact.citation_check = CitationCheck.NO_CITATION
            fact.flags.append("No valid deck citation; treat as unsupported.")
        elif not fact.excerpt:
            fact.citation_check = CitationCheck.NO_EXCERPT
        else:
            pages_text = "\n".join(deck.unit(n).all_text for n in fact.source_pages)  # type: ignore[union-attr]
            if excerpt_found(fact.excerpt, pages_text):
                fact.citation_check = CitationCheck.VERIFIED
            elif excerpt_found(fact.excerpt, "\n".join(u.all_text for u in deck.units)):
                fact.citation_check = CitationCheck.NOT_FOUND
                fact.flags.append(f"Excerpt appears in the deck but not on the cited {label}(s).")
            else:
                fact.citation_check = CitationCheck.NOT_FOUND
                fact.flags.append("Excerpt not found in the extracted deck text "
                                  "(may come from an image, or may be inaccurate).")

        if fact.status == EvidenceStatus.CALCULATED:
            if not fact.formula:
                fact.flags.append("Calculated value has no formula; cannot be checked.")
            else:
                result, target = evaluate_formula(fact.formula), parse_value(fact.value)
                if result is None:
                    fact.flags.append("Formula could not be evaluated automatically.")
                elif target is not None and not any(
                    _close(result, c) for _, cands in numbers_in(fact.value) for c in cands
                ):
                    fact.flags.append(f"Formula evaluates to {result:,.4g}, which does not match the stated value.")
        elif fact.status == EvidenceStatus.INFERRED:
            fact.flags.append("Inferred, not stated in the deck.")
        facts.append(fact)

    mark_conflicts(facts, label)
    return facts


_VAGUE_PERIOD = re.compile(r"\b(current|currently|today|now|to date|latest|undated|recent)\b")


def _periods_compatible(a: str | None, b: str | None) -> bool:
    """Equal periods, or one is blank/'current' (an undated figure may be the same one)."""
    na, nb = normalize(a or ""), normalize(b or "")
    return na == nb or any(not p or _VAGUE_PERIOD.search(p) for p in (na, nb))


def _values_differ(a: Fact, b: Fact) -> bool:
    va, vb = parse_value(a.value), parse_value(b.value)
    if va is not None and vb is not None:
        return not _close(va, vb)
    return normalize(a.value) != normalize(b.value)


def mark_conflicts(facts: list[Fact], unit_label: str = "slide") -> list[Inconsistency]:
    """Mark facts that share a key and basis, have compatible periods and differ in value."""
    groups: dict[tuple[str, str], list[Fact]] = {}
    for f in facts:
        if f.status != EvidenceStatus.MISSING and f.origin == Origin.DECK:
            key = re.sub(r"[^a-z0-9]", "_", f.key.lower()).strip("_")
            groups.setdefault((key, f.basis.value), []).append(f)
    found: list[Inconsistency] = []
    for members in groups.values():
        group = [x for x in members if any(
            x is not y and _periods_compatible(x.period, y.period) and _values_differ(x, y)
            for y in members)]
        if not group:
            continue
        for f in group:
            others = ", ".join(o.id for o in group if o is not f)
            f.status = EvidenceStatus.CONFLICTING
            msg = f"Conflicts with {others}; neither value has been chosen."
            if msg not in f.flags:
                f.flags.append(msg)
        found.append(Inconsistency(
            description=f"Conflicting values for '{group[0].label}'"
                        + (f" ({group[0].period})" if group[0].period else ""),
            values=[f"{f.value} ({unit_label} {', '.join(map(str, f.source_pages)) or '?'})" for f in group],
            source_pages=sorted({p for f in group for p in f.source_pages}),
        ))
    return found


def merge_inconsistencies(model: list[Inconsistency], detected: list[Inconsistency]) -> list[Inconsistency]:
    merged = list(model)
    for d in detected:
        if not any(set(d.source_pages) <= set(m.source_pages) and d.source_pages for m in model):
            merged.append(d)
    return merged


def apply_user_correction(fact: Fact, new_value: str, unit: str | None = None,
                          period: str | None = None) -> Fact:
    """Record a user correction without fabricating a deck citation."""
    updated = fact.model_copy(deep=True)
    if updated.origin == Origin.DECK and updated.original_value is None:
        updated.original_value = fact.value
    updated.value = new_value.strip() or NOT_PROVIDED
    if unit is not None:
        updated.unit = unit or None
    if period is not None:
        updated.period = period or None
    updated.origin = Origin.USER
    updated.source_pages, updated.excerpt = [], None
    updated.citation_check = CitationCheck.USER
    updated.status = EvidenceStatus.MISSING if is_missing_value(new_value) else EvidenceStatus.STATED
    updated.flags = [f for f in updated.flags if not f.startswith(("Excerpt", "Removed citation", "No valid"))]
    updated.flags.append("User-provided correction; not sourced from the deck.")
    return updated


def unsupported_figures(text: str, deck: ExtractedDeck, facts: list[Fact],
                        extra_sources: list[str] | None = None) -> list[str]:
    """Figures in generated text that match nothing in the deck, facts or user input."""
    known: list[float] = []
    sources = [u.all_text for u in deck.units] + [f.value for f in facts] + [f.formula or "" for f in facts]
    sources += extra_sources or []
    for src in sources:
        for _, cands in numbers_in(src):
            known.extend(cands)
    unmatched = []
    for token, cands in numbers_in(text):
        if not any(_close(c, k) for c in cands for k in known):
            unmatched.append(token)
    return list(dict.fromkeys(unmatched))
