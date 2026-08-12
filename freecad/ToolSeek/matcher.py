# SPDX-License-Identifier: LGPL-2.1-or-later
"""Filter and rank command search results."""

from __future__ import annotations

import re

from .indexer import CommandInfo

# Split CamelCase / PascalCase and runs of digits.
# "BSplineComb" → B, Spline, Comb; "CreateLine" → Create, Line.
_CAMEL_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z]|\d|$)|[A-Z]?[a-z]+|\d+")

# Score bands (lower is better). Label hits beat id hits; fuzzy is last resort.
_LABEL = 0
_ID = 80

_EXACT = 0
_PREFIX = 5
_WHOLE_WORD = 12
_WORD_PREFIX = 18
# Mid-token substrings (e.g. "line" inside "Spline") are intentionally weak.
_MID_TOKEN = 95
_FUZZY = 130

_ACTIVE_WB_BONUS = -30
_OTHER_WB_PENALTY = 18
_UNKNOWN_WB_PENALTY = 8
_INACTIVE_PENALTY = 500


def _tokens(text: str) -> list[str]:
    """Tokenize on non-alnum and CamelCase boundaries (casefolded)."""
    if not text:
        return []
    tokens: list[str] = []
    for part in re.split(r"[^A-Za-z0-9]+", text):
        if not part:
            continue
        pieces = _CAMEL_RE.findall(part)
        if pieces:
            tokens.extend(p.casefold() for p in pieces)
        else:
            tokens.append(part.casefold())
    return tokens


def _edit_distance(a: str, b: str, limit: int) -> int | None:
    """Levenshtein distance, or None if greater than *limit*."""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if abs(la - lb) > limit:
        return None
    if la == 0:
        return lb if lb <= limit else None
    if lb == 0:
        return la if la <= limit else None

    prev = list(range(lb + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i] + [0] * lb
        row_min = cur[0]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            cur[j] = min(
                prev[j] + 1,
                cur[j - 1] + 1,
                prev[j - 1] + cost,
            )
            if cur[j] < row_min:
                row_min = cur[j]
        if row_min > limit:
            return None
        prev = cur
    dist = prev[lb]
    return dist if dist <= limit else None


def _is_subsequence(needle: str, haystack: str) -> bool:
    it = iter(haystack)
    return all(ch in it for ch in needle)


def _fuzzy_penalty(term: str, tokens: list[str], text_fold: str) -> int | None:
    """
    Lightweight fuzzy match against tokens / full text.

    Accepts small typos vs individual tokens, or (for longer terms) a
    subsequence of the full text. Returns an extra penalty, or None.
    """
    if len(term) < 2:
        return None

    max_dist = 1 if len(term) < 6 else 2
    best: int | None = None
    for word in tokens:
        dist = _edit_distance(term, word, max_dist)
        if dist is None or dist == 0:
            # dist 0 is an exact token hit handled elsewhere
            continue
        penalty = 15 * dist + max(0, abs(len(word) - len(term)))
        if best is None or penalty < best:
            best = penalty

    if best is not None:
        return best

    # Subsequence only for longer needles to limit noise ("ln" is too weak).
    if len(term) >= 3 and _is_subsequence(term, text_fold):
        return 45
    return None


def _score_field(
    term: str, text: str, field_base: int, *, allow_fuzzy: bool = True
) -> int | None:
    """Score *term* against one field. Lower is better; None = no match."""
    fold = text.casefold()
    if not fold:
        return None

    if fold == term:
        return field_base + _EXACT
    if fold.startswith(term):
        return field_base + _PREFIX

    tokens = _tokens(text)
    if term in tokens:
        return field_base + _WHOLE_WORD

    for i, word in enumerate(tokens):
        if word.startswith(term):
            # Leading token beats a later token prefix.
            return field_base + (_WORD_PREFIX if i == 0 else _WORD_PREFIX + 6)

    # Mid-token / embedded substring: keep as a weak path only.
    # "line" inside token "spline" must not beat whole-token "line".
    for word in tokens:
        idx = word.find(term)
        if idx > 0:
            return field_base + _MID_TOKEN + min(idx, 10)

    # Contiguous match across the folded string that is not a token hit
    # (e.g. odd punctuation). Still weak.
    idx = fold.find(term)
    if idx >= 0:
        return field_base + _MID_TOKEN + min(idx, 10)

    if allow_fuzzy:
        fuzzy = _fuzzy_penalty(term, tokens, fold)
        if fuzzy is not None:
            return field_base + _FUZZY + fuzzy

    return None


def _score_term(
    term: str, menu_text: str, name: str, *, allow_fuzzy: bool = True
) -> int | None:
    """Best score for one query term across menu label and command id."""
    label = _score_field(term, menu_text, _LABEL, allow_fuzzy=allow_fuzzy)
    ident = _score_field(term, name, _ID, allow_fuzzy=allow_fuzzy)
    if label is None:
        return ident
    if ident is None:
        return label
    return min(label, ident)


def _workbench_adjustment(cmd: CommandInfo) -> int:
    if cmd.current_workbench:
        return _ACTIVE_WB_BONUS
    if cmd.workbench_id or cmd.workbench_name:
        return _OTHER_WB_PENALTY
    return _UNKNOWN_WB_PENALTY


def score(
    query: str, cmd: CommandInfo, *, allow_fuzzy: bool = True
) -> int | None:
    """
    Rank how well *cmd* matches *query*.

    Each whitespace-separated term must match menu text or command id
    (case-insensitive), including lightweight fuzzy matches when
    *allow_fuzzy* is True. Returns None if any term fails; otherwise a
    score (lower is better).

    Ranking priority (high → low):
      menu label exact/prefix/token → command-id token hits →
      mid-token substring → fuzzy → active-workbench boost /
      other-workbench penalty → inactive.
    """
    folded = query.casefold().strip()
    if not folded:
        # Empty query: current workbench and active commands float up.
        total = 0
        total += _workbench_adjustment(cmd)
        if not cmd.active:
            total += _INACTIVE_PENALTY
        return total

    terms = folded.split()
    total = 0
    for term in terms:
        term_score = _score_term(
            term, cmd.menu_text, cmd.name, allow_fuzzy=allow_fuzzy
        )
        if term_score is None:
            return None
        total += term_score

    total += _workbench_adjustment(cmd)
    if not cmd.active:
        total += _INACTIVE_PENALTY
    return total


def filter_commands(
    query: str,
    commands: list[CommandInfo],
    *,
    allow_fuzzy: bool = True,
) -> list[CommandInfo]:
    """Return commands matching *query*, best matches first."""
    scored: list[tuple[int, CommandInfo]] = []
    for cmd in commands:
        s = score(query, cmd, allow_fuzzy=allow_fuzzy)
        if s is not None:
            scored.append((s, cmd))

    scored.sort(
        key=lambda pair: (
            pair[0],
            pair[1].menu_text.casefold(),
            pair[1].name.casefold(),
        )
    )
    return [cmd for _, cmd in scored]
