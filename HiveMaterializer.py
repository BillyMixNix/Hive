import json
import re
from datetime import datetime
from pathlib import Path


_TYPE_DIRS = {
    "character": "characters",
    "location": "locations",
    "faction": "factions",
    "item": "items",
    "event": "events",
    "note": "notes",
    "decision": "decisions",
    "lore": "lore",
    "rule": "rules",
    "session": "sessions",
}


def _slugify(name):
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "_", slug)
    return slug.strip("_")


class HiveMaterializer:
    """
    Writes declared entities and facts to project files.

    The project_dir is the root of the pilot's project — not Hive's own
    codebase. Each entity gets a markdown file. An index at
    <project_dir>/.hive_index.json tracks what exists.
    """

    def __init__(self, project_dir="."):
        self.project_dir = Path(project_dir)
        self.index_path = self.project_dir / ".hive_index.json"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def materialize(self, name, entity_type, content, target_file=None, project=None):
        """Write an entity to disk. Creates or updates the file.

        Returns a dict with file path, action (created/updated), and name.
        """
        entity_type = entity_type.lower().strip()
        target = Path(target_file) if target_file else self._infer_path(name, entity_type)

        full_path = self.project_dir / target
        full_path.parent.mkdir(parents=True, exist_ok=True)

        action = "updated" if full_path.exists() else "created"
        full_path.write_text(
            self._render(name, entity_type, content),
            encoding="utf-8",
        )

        self._update_index(name, entity_type, str(target), project)

        return {
            "file": str(target),
            "action": action,
            "name": name,
            "entity_type": entity_type,
            "project": project,
        }

    def list_entities(self, entity_type=None, project=None):
        """Return index entries, optionally filtered by type or project."""
        index = self._load_index()
        results = list(index.values())
        if entity_type:
            results = [e for e in results if e.get("entity_type") == entity_type.lower()]
        if project:
            results = [e for e in results if e.get("project") == project]
        results.sort(key=lambda e: e.get("updated_at", ""), reverse=True)
        return results

    def read_entity(self, name, entity_type):
        """Read a materialized entity's file content. Returns None if not found."""
        index = self._load_index()
        key = self._index_key(name, entity_type)
        entry = index.get(key)
        if not entry:
            return None
        path = self.project_dir / entry["file"]
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def changelog(self, limit=20):
        """Return recent materialization events from the index."""
        index = self._load_index()
        entries = sorted(
            index.values(),
            key=lambda e: e.get("updated_at", ""),
            reverse=True,
        )
        return entries[:limit]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _infer_path(self, name, entity_type):
        folder = _TYPE_DIRS.get(entity_type, entity_type + "s")
        return Path(folder) / (_slugify(name) + ".md")

    def _render(self, name, entity_type, content):
        lines = [
            f"# {name}",
            f"**Type:** {entity_type.title()}",
            f"*Last updated: {datetime.utcnow().strftime('%Y-%m-%d')}*",
            "",
        ]
        if isinstance(content, dict):
            for key, value in content.items():
                if value:
                    lines.append(f"## {key.replace('_', ' ').title()}")
                    lines.append(str(value))
                    lines.append("")
        elif isinstance(content, str) and content.strip():
            lines.append(content.strip())
        return "\n".join(lines) + "\n"

    def _index_key(self, name, entity_type):
        return f"{entity_type.lower()}:{_slugify(name)}"

    def _load_index(self):
        if self.index_path.exists():
            try:
                return json.loads(self.index_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _update_index(self, name, entity_type, file_path, project):
        index = self._load_index()
        key = self._index_key(name, entity_type)
        index[key] = {
            "name": name,
            "entity_type": entity_type.lower(),
            "file": file_path,
            "project": project,
            "updated_at": datetime.utcnow().isoformat(),
        }
        self.index_path.write_text(
            json.dumps(index, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
