"""
Native Templater-subset renderer (Day77.01).

Kept dependency-free (stdlib only) so it's unit-testable in isolation, mirroring
the vault_permissions.py extraction pattern from Day75.05. Evaluates the honest
subset of Templater `<% %>` syntax actually used by the MegaMem template corpus
so create_note_with_template can render templates without the Templater plugin
installed in the target vault. Skeleton content outside `<% %>` constructs
passes through byte-identical — only the dynamic constructs are evaluated.

Supported constructs:
  - <%"literal"%> / <%'literal'%>        — literal string output
  - <% tp.file.title %>                  — new note's title
  - <% tp.date.now("FORMAT") %>          — current date/time, Moment-subset format
  - <% tp.file.creation_date("FORMAT") %> — same as now() (note is being created)
  - <% tp.file.last_modified_date("FORMAT") %> — same as now() (freshly created)
  - <% tp.file.move("folder/path") %>    — captured as target_folder_from_template,
                                            renders to empty string (Templater semantics)
  - Optional `-`/`*` tag-prefix variants (<%- %>, <%* %>) are matched identically —
    MegaMem doesn't distinguish whitespace-control/execution-only tags.

Anything else inside `<% %>` is unsupported: no partial render — the whole
render fails, naming every unsupported construct found, so callers can decide
to fall back to legacy Templater (if installed + template local) or error hard.

@purpose: Deterministic, Templater-free rendering of the supported syntax subset
@depends: nothing beyond stdlib (re, datetime)
@results: {rendered_content, target_folder_from_template, unsupported} consumed
          by ObsidianCLI.create_note_with_template
"""

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

# Matches a single <% ... %> construct (optional -/* tag-prefix variants).
# DOTALL so multi-line expressions (rare, none in corpus) don't break matching.
_CONSTRUCT_RE = re.compile(r"<%[-*]?\s*(.*?)\s*%>", re.DOTALL)

_STRING_LITERAL_RE = re.compile(r'^"([^"]*)"$|^\'([^\']*)\'$')
_TP_FILE_TITLE_RE = re.compile(r'^tp\.file\.title$')
_TP_DATE_NOW_RE = re.compile(r'^tp\.date\.now\(\s*"([^"]*)"\s*\)$')
_TP_FILE_CREATION_DATE_RE = re.compile(r'^tp\.file\.creation_date\(\s*"([^"]*)"\s*\)$')
_TP_FILE_LAST_MODIFIED_DATE_RE = re.compile(r'^tp\.file\.last_modified_date\(\s*"([^"]*)"\s*\)$')
_TP_FILE_MOVE_RE = re.compile(r'^tp\.file\.move\(\s*"([^"]*)"\s*\)$')

# Moment.js-style date tokens we support (the only ones the corpus uses).
_DATE_TOKEN_RE = re.compile(r"YYYY|MM|DD|HH|mm|ss")
_TOKEN_TO_STRFTIME = {
    "YYYY": "%Y", "MM": "%m", "DD": "%d", "HH": "%H", "mm": "%M", "ss": "%S",
}


def format_date(fmt: str, dt: datetime) -> str:
    """Render a Moment.js-style date format string using our supported token subset.
    Unsupported tokens/literal characters pass through unchanged.
    """
    return _DATE_TOKEN_RE.sub(lambda m: dt.strftime(_TOKEN_TO_STRFTIME[m.group(0)]), fmt)


def render_template(
    content: str,
    *,
    file_title: str,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Render the honest Templater subset. Skeleton content outside `<% %>`
    constructs passes through byte-identical.

    Returns:
        {
            "rendered_content": str | None,   # None if any unsupported construct found
            "target_folder_from_template": str | None,
            "unsupported": [str, ...],        # de-duplicated raw construct text
        }
    No partial render — if `unsupported` is non-empty, `rendered_content` is None.
    """
    now = now or datetime.now()
    unsupported: List[str] = []
    seen_unsupported: set = set()
    target_folder: Optional[str] = None

    def _replace(match: "re.Match[str]") -> str:
        nonlocal target_folder
        raw = match.group(0)
        expr = match.group(1).strip()

        lit = _STRING_LITERAL_RE.match(expr)
        if lit:
            return lit.group(1) if lit.group(1) is not None else lit.group(2)

        if _TP_FILE_TITLE_RE.match(expr):
            return file_title

        m = _TP_DATE_NOW_RE.match(expr)
        if m:
            return format_date(m.group(1), now)

        m = _TP_FILE_CREATION_DATE_RE.match(expr)
        if m:
            return format_date(m.group(1), now)

        m = _TP_FILE_LAST_MODIFIED_DATE_RE.match(expr)
        if m:
            return format_date(m.group(1), now)

        m = _TP_FILE_MOVE_RE.match(expr)
        if m:
            target_folder = m.group(1)
            return ""  # tp.file.move renders to empty string under real Templater too

        if raw not in seen_unsupported:
            seen_unsupported.add(raw)
            unsupported.append(raw)
        return raw  # placeholder text; discarded entirely if unsupported is non-empty

    rendered = _CONSTRUCT_RE.sub(_replace, content)

    if unsupported:
        return {
            "rendered_content": None,
            "target_folder_from_template": None,
            "unsupported": unsupported,
        }

    return {
        "rendered_content": rendered,
        "target_folder_from_template": target_folder,
        "unsupported": [],
    }
