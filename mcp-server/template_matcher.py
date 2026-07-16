"""
Template resolution matcher (Day77.01).

Kept dependency-free (stdlib only) so the matching ladder is unit-testable in
isolation, mirroring the vault_permissions.py extraction pattern from Day75.05.
No vault I/O lives here — callers (ObsidianCLI) fetch candidate lists per
source (filenames in filename mode, registry entries in registry mode) and
this module resolves request_type against them.

Validated 2026-07-16: no registry-parsing code exists anywhere in the
codebase prior to this module — registry mode is a net-new build, not a
refactor of existing logic. Filename-mode matching already existed (fuzzy
ladders duplicated across file_tools.py / obsidian_cli.py / WebSocketService.ts);
this module unifies the ladder into one tested implementation for the CLI path.

@purpose: Resolve request_type against ordered per-source candidate lists
@depends: nothing beyond stdlib (dataclasses)
@results: MatchResult consumed by ObsidianCLI.create_note_with_template for
          per-source and cross-source (multi-source, first-match-wins) resolution
"""

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Set

_WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass
class TemplateCandidate:
    """A single resolvable template — either a filename-mode entry (name =
    filename stem, no metadata) or a registry-mode entry with metadata.
    """
    name: str                      # filename stem or registry template_name
    source_label: str = ""         # which configured source this came from
    source_index: int = -1         # index into the caller's ordered source list
    path: str = ""                 # vault-relative template file path
    when_to_use: Optional[str] = None
    category: Optional[str] = None
    folder: Optional[str] = None   # registry-mode default folder, if any

    def to_dict(self) -> Dict[str, Any]:
        """Registry-mode candidates include metadata; filename-mode candidates
        are just names — omit None fields so filename mode responses stay lean.
        """
        d: Dict[str, Any] = {"name": self.name, "source": self.source_label}
        if self.when_to_use is not None:
            d["when_to_use"] = self.when_to_use
        if self.category is not None:
            d["category"] = self.category
        return d


def match_candidates(request_type: str, candidates: List[TemplateCandidate]) -> Dict[str, Any]:
    """
    Exact (case-insensitive) -> startswith/prefix -> substring-fuzzy ladder.
    First match wins within this single (already source-ordered) candidate list.

    Returns:
        {"matched": TemplateCandidate | None, "confident": bool, "candidates": [...]}
    confident=False + matched=None means: return top candidates instead of
    guessing — the structured candidate-return response, not an error.
    """
    if not request_type or not candidates:
        return {"matched": None, "confident": False, "candidates": list(candidates)}

    request_lower = request_type.strip().lower()

    for c in candidates:
        if c.name.strip().lower() == request_lower:
            return {"matched": c, "confident": True, "candidates": []}

    for c in candidates:
        name_lower = c.name.strip().lower()
        if name_lower.startswith(request_lower) or request_lower.startswith(name_lower):
            return {"matched": c, "confident": True, "candidates": []}

    for c in candidates:
        name_lower = c.name.strip().lower()
        if request_lower in name_lower or name_lower in request_lower:
            return {"matched": c, "confident": True, "candidates": []}

    return {"matched": None, "confident": False, "candidates": list(candidates)}


def resolve_across_sources(
    request_type: str,
    source_candidates: List[List[TemplateCandidate]],
    override_index: Optional[int] = None,
) -> Dict[str, Any]:
    """
    First-match-wins across ordered sources (personal-then-company precedence,
    or whatever order the caller's settings define). `override_index` pins
    resolution to a single source's candidate list — the `template_source`
    per-call override param.

    Returns:
        {"matched": TemplateCandidate | None, "confident": bool, "candidates": [...]}
    When no source yields a confident match, "candidates" is the union across
    all considered sources, de-duplicated by name (first occurrence — i.e.
    highest-precedence source — wins the metadata shown).
    """
    lists = source_candidates
    if override_index is not None and 0 <= override_index < len(source_candidates):
        lists = [source_candidates[override_index]]

    for candidates in lists:
        result = match_candidates(request_type, candidates)
        if result["confident"]:
            return result

    seen: set = set()
    merged: List[TemplateCandidate] = []
    for candidates in lists:
        for c in candidates:
            key = c.name.strip().lower()
            if key not in seen:
                seen.add(key)
                merged.append(c)

    return {"matched": None, "confident": False, "candidates": merged}


def _words(text: Optional[str]) -> Set[str]:
    return set(_WORD_RE.findall(text.lower())) if text else set()


def rank_candidates(request_type: str, candidates: List[TemplateCandidate]) -> List[TemplateCandidate]:
    """
    Rank no-confident-match candidates by relevance to request_type instead
    of leaving them in source/listing order — the merged list from
    resolve_across_sources() comes back in per-source append order (itself
    usually alphabetical, since it mirrors the CLI's file listing), which
    made an unrelated template look like the top "match" purely because its
    source happened to be listed first (Task 3b, Day77.01 Rev 4: observed
    live, "TPL Widget" surfaced 10 alphabetical Personal-only candidates
    with no relevance to the request and no Company entries at all).

    Scores on word overlap against both the template name and (when a
    registry populated it) the when_to_use text, with a whole-string
    similarity ratio as a tiebreaker for partial-word matches (e.g.
    "Contract" vs "Contracts"). Pure stdlib (re, difflib) — no I/O,
    unit-testable in isolation like the rest of this module. Callers should
    enrich candidates with registry metadata (when available) before
    ranking, so when_to_use text can contribute to the score.
    """
    request_words = _words(request_type)

    def score(c: TemplateCandidate) -> tuple:
        overlap = len(request_words & _words(c.name)) * 2 + len(request_words & _words(c.when_to_use))
        ratio = SequenceMatcher(None, request_type.strip().lower(), c.name.strip().lower()).ratio()
        return (overlap, ratio)

    return sorted(candidates, key=score, reverse=True)
