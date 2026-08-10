#!/usr/bin/env python3
"""Render upstream release notes newer than our pinned commit as Markdown.

Called by .github/workflows/theme-watch.yml. Lives in its own file rather than
as an inline heredoc because embedding Python in a YAML block scalar breaks the
workflow parser.

Usage: format-releases.py <releases.jsonl> <pinned_iso_date>

Input is one JSON object per line, as emitted by:
    gh api repos/OWNER/REPO/releases --jq '.[] | {tag, published, body}'
"""

import json
import sys

# GitHub rejects issue bodies over ~65k characters, and a wall of release notes
# is unreadable anyway. Cap each release; the full patch ships as an artifact.
MAX_BODY_CHARS = 4000


def main() -> int:
    if len(sys.argv) < 2:
        print("_(release notes unavailable)_")
        return 0

    path = sys.argv[1]
    pinned_date = sys.argv[2] if len(sys.argv) > 2 else ""

    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        print("_(release notes unavailable)_")
        return 0

    shown = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            release = json.loads(line)
        except json.JSONDecodeError:
            # A non-JSON line means the gh call fell back to an error string.
            continue

        published = release.get("published") or ""
        # Only report what landed after the commit we are pinned to.
        if pinned_date and published <= pinned_date:
            continue

        tag = release.get("tag") or "(untagged)"
        body = (release.get("body") or "").strip()
        if len(body) > MAX_BODY_CHARS:
            body = body[:MAX_BODY_CHARS] + "\n\n_…truncated, see the full release on GitHub._"

        shown += 1
        print(f"<details><summary><b>{tag}</b> — {published[:10]}</summary>\n")
        print(body if body else "_(no release notes)_")
        print("\n</details>\n")

    if shown == 0:
        print(
            "_No tagged release published since our pinned commit — "
            "the changes above are unreleased commits on `main`._"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
