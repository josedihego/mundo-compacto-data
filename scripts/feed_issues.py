#!/usr/bin/env python3
"""Open a GitHub issue for each feed failing several runs in a row; close it on recovery.

Reads state/feed_alerts.json (written by pipeline.build). Needs the `gh` CLI and GH_TOKEN.
"""
import json
import subprocess
import sys
from pathlib import Path

LABEL = "feed-failure"


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def open_issue_number(title: str) -> int | None:
    rows = json.loads(gh("issue", "list", "--state", "open", "--label", LABEL,
                         "--json", "number,title", "--limit", "100"))
    return next((r["number"] for r in rows if r["title"] == title), None)


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "state/feed_alerts.json")
    if not path.exists():
        return 0
    alerts = json.loads(path.read_text())
    if not alerts["failing"] and not alerts["recovered"]:
        return 0
    gh("label", "create", LABEL, "--color", "B60205", "--description", "An RSS feed keeps failing", "--force")

    for f in alerts["failing"]:
        title = f"Feed failing: {f['name']}"
        if open_issue_number(title) is None:
            body = (f"The feed **{f['name']}** (`{f['id']}`) has failed {f['fails']} runs in a row.\n\n"
                    f"- URL: {f['url']}\n- Last error: `{f['error']}`\n\n"
                    "Fix or replace the URL in `config/feeds.json`. "
                    "This issue closes automatically when the feed recovers.")
            gh("issue", "create", "--title", title, "--body", body, "--label", LABEL)
            print(f"opened: {title}")

    for f in alerts["recovered"]:
        n = open_issue_number(f"Feed failing: {f['name']}")
        if n is not None:
            gh("issue", "close", str(n), "--comment", "Feed recovered; closing automatically.")
            print(f"closed #{n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
