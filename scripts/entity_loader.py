#!/usr/bin/env python3
"""Print a summary of materialized project entities for injection into session context."""
import json
from pathlib import Path


def load_index(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def format_entities(index):
    if not index:
        return ""

    by_type = {}
    for entry in index.values():
        t = entry.get("entity_type", "unknown")
        by_type.setdefault(t, []).append(entry)

    lines = ["=== Project Entities ==="]

    projects = {e.get("project") for e in index.values() if e.get("project")}
    if projects:
        lines.append(f"Projects: {', '.join(sorted(projects))}")
    lines.append(f"{len(index)} entities across {len(by_type)} types")
    lines.append("")

    for entity_type in sorted(by_type):
        entries = sorted(by_type[entity_type], key=lambda e: e.get("name", ""))
        lines.append(f"{entity_type.title()}s ({len(entries)}):")
        for entry in entries:
            project_tag = f" [{entry['project']}]" if entry.get("project") else ""
            lines.append(f"  - {entry['name']}{project_tag} → {entry['file']}")
        lines.append("")

    lines.append("=== End Project Entities ===")
    return "\n".join(lines)


def main():
    repo_root = Path(__file__).parent.parent
    index_path = repo_root / ".hive_index.json"

    if not index_path.exists():
        print(".hive_index.json not found — no materialized entities.")
        return

    index = load_index(index_path)
    if not index:
        print(".hive_index.json is empty.")
        return

    print(format_entities(index))


if __name__ == "__main__":
    main()
