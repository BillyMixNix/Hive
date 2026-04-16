from pathlib import Path
from datetime import datetime
import copy
import json


class HiveStateManager:
    """
    Centralized authoritative state for Hive.

    Responsibilities:
    - track current effective file text
    - track version history per file
    - record patch apply / rollback events
    - provide one shared source of truth for agents
    """

    def __init__(self, snapshot_path="hive_state_snapshot.json", repo_root="."):
        self.snapshot_path = Path(snapshot_path)
        self.repo_root = Path(repo_root)

        self.repo_state = {
            "repo_map": None,
            "updated_at": None,
        }
        self.file_state = {}
        self.patch_history = {}
        self.task_state = {}
        self.agent_state = {}
        self.observability = self._build_default_observability_snapshot()

    def _build_default_observability_snapshot(self):
        return {
            "current": {
                "active_goal": None,
                "active_task_id": None,
                "active_plan_id": None,
                "active_child_task_id": None,
                "current_child_task_title": None,
                "task_status": None,
                "target_file": None,
                "target_symbol": None,
                "change_intent": None,
                "expected_operation": None,
                "completion_cues": [],
                "updated_at": None,
            },
            "last_patch": {
                "target_file": None,
                "target_symbol": None,
                "patch_status": None,
                "validation_outcome": None,
                "rejection_reason": None,
                "reflection_verdict": None,
                "confidence": None,
                "timestamp": None,
            },
            "failures": {
                "recent": [],
                "counts_by_category": {},
                "updated_at": None,
            },
            "lessons": {
                "recent": [],
                "updated_at": None,
            },
            "system": {
                "repo_loaded": False,
                "known_files_count": 0,
                "known_symbols_count": 0,
                "active_route": None,
                "active_mode": None,
                "updated_at": None,
            },
        }

    def _now(self):
        return datetime.utcnow().isoformat()

    def _resolve_repo_path(self, target_file):
        path = Path(target_file)
        if path.is_absolute():
            return path
        return self.repo_root / path

    def has_file_state(self, target_file):
        return target_file in self.file_state

    def get_file_state(self, target_file):
        state = self.file_state.get(target_file)
        return copy.deepcopy(state) if state else None

    def get_file_text(self, target_file):
        state = self.file_state.get(target_file)
        if not state:
            return None
        return state.get("content")

    def set_repo_map(self, repo_map_data):
        self.repo_state["repo_map"] = copy.deepcopy(repo_map_data)
        self.repo_state["updated_at"] = self._now()
        known_files = repo_map_data.get("known_files") or []
        symbol_to_file = repo_map_data.get("symbol_to_file") or {}
        self.update_observability_section(
            "system",
            {
                "repo_loaded": True,
                "known_files_count": len(known_files),
                "known_symbols_count": len(symbol_to_file),
            },
        )
        return True

    def rebuild_repo_map(self):
        from repo_map import RepoMap

        repo_map = RepoMap(root=self.repo_root)
        self.set_repo_map(repo_map.build())
        return self.get_repo_map()

    def get_repo_map(self):
        data = self.repo_state.get("repo_map")
        return copy.deepcopy(data) if data else None

    def get_known_files(self):
        repo_map = self.get_repo_map() or {}
        files = repo_map.get("known_files") or []
        return list(files)

    def get_file_imports(self, file_name):
        repo_map = self.get_repo_map() or {}
        return list((repo_map.get("file_imports") or {}).get(file_name, []))

    def get_file_imported_by(self, file_name):
        repo_map = self.get_repo_map() or {}
        return list((repo_map.get("file_imported_by") or {}).get(file_name, []))

    def get_symbol_references(self, symbol):
        repo_map = self.get_repo_map() or {}
        return list((repo_map.get("symbol_references") or {}).get(symbol, []))

    def get_related_files_for_symbol(self, symbol, depth=1):
        repo_map = self.get_repo_map() or {}
        if not repo_map:
            return []

        owner_file = repo_map.get("symbol_to_file", {}).get(symbol)
        if not owner_file:
            return []

        related = {owner_file}
        frontier = {owner_file}

        for _ in range(depth):
            next_frontier = set()
            for file_name in frontier:
                next_frontier.update((repo_map.get("file_imports") or {}).get(file_name, []))
                next_frontier.update((repo_map.get("file_imported_by") or {}).get(file_name, []))

                for sym, refs in (repo_map.get("symbol_references") or {}).items():
                    if sym == symbol or repo_map.get("symbol_to_file", {}).get(sym) == file_name:
                        for ref_symbol in refs:
                            ref_file = repo_map.get("symbol_to_file", {}).get(ref_symbol)
                            if ref_file:
                                next_frontier.add(ref_file)

            next_frontier -= related
            if not next_frontier:
                break

            related.update(next_frontier)
            frontier = next_frontier

        return sorted(related)

    def resolve_symbol_to_file(self, symbol):
        repo_map = self.get_repo_map() or {}
        symbol_to_file = repo_map.get("symbol_to_file") or {}
        return symbol_to_file.get(symbol)

    def resolve_symbol_span(self, symbol_id_or_symbol, target_file=None):
        repo_map = self.get_repo_map() or {}
        if not repo_map:
            return None

        symbol_spans = repo_map.get("symbol_spans") or {}
        symbol_to_span = repo_map.get("symbol_to_span") or {}

        if symbol_id_or_symbol in symbol_spans:
            return copy.deepcopy(symbol_spans[symbol_id_or_symbol])

        if target_file:
            direct_id = f"{target_file}::{symbol_id_or_symbol}"
            direct_match = symbol_spans.get(direct_id)
            if direct_match:
                return copy.deepcopy(direct_match)

            for _symbol_id, record in symbol_spans.items():
                if not isinstance(record, dict):
                    continue
                if record.get("file") == target_file and record.get("symbol") == symbol_id_or_symbol:
                    return copy.deepcopy(record)

        record = symbol_to_span.get(symbol_id_or_symbol)
        return copy.deepcopy(record) if record else None

    def get_symbol_span(self, target_file, target_symbol):
        return self.resolve_symbol_span(
            target_symbol,
            target_file=target_file,
        )

    def get_symbols_for_file(self, file_name):
        repo_map = self.get_repo_map() or {}
        file_symbols = repo_map.get("file_symbols") or {}
        return list(file_symbols.get(file_name, []))

    def get_file_summary(self, file_name):
        repo_map = self.get_repo_map() or {}
        file_summaries = repo_map.get("file_summaries") or {}
        summary = file_summaries.get(file_name)
        return copy.deepcopy(summary) if summary else None

    def get_file_symbol_inventory(self, file_name):
        summary = self.get_file_summary(file_name) or {}
        return list(summary.get("symbol_inventory") or [])

    def get_file_route_branch_inventory(self, file_name):
        summary = self.get_file_summary(file_name) or {}
        return list(summary.get("route_branch_inventory") or [])

    def set_file_text(self, target_file, content, source="unknown", patch_id=None):
        previous = self.file_state.get(target_file)

        version_entry = {
            "timestamp": self._now(),
            "source": source,
            "patch_id": patch_id,
            "content": content,
        }

        if target_file not in self.patch_history:
            self.patch_history[target_file] = []

        self.file_state[target_file] = {
            "target_file": target_file,
            "content": content,
            "source": source,
            "last_patch_id": patch_id,
            "updated_at": version_entry["timestamp"],
            "previous_source": previous.get("source") if previous else None,
        }

        self.patch_history[target_file].append(version_entry)
        return True

    def load_file_from_disk(self, target_file):
        path = self._resolve_repo_path(target_file)
        if not path.exists():
            raise FileNotFoundError(f"Target file not found: {target_file}")

        content = path.read_text(encoding="utf-8")
        self.set_file_text(
            target_file,
            content,
            source="disk",
            patch_id=None,
        )
        return content

    def get_effective_file_text(self, target_file):
        """
        Return current authoritative file text.
        Refresh from disk when cached state is stale.
        """
        disk_path = self._resolve_repo_path(target_file)
        cached = self.get_file_text(target_file)

        if disk_path.exists():
            disk_content = disk_path.read_text(encoding="utf-8")
            if cached != disk_content:
                self.set_file_text(
                    target_file,
                    disk_content,
                    source="disk",
                    patch_id=None,
                )
                return disk_content

        if cached is not None:
            return cached
        return self.load_file_from_disk(target_file)

    def sync_tracked_files_with_disk(self):
        changed = []

        for target_file in list(self.file_state.keys()):
            disk_path = self._resolve_repo_path(target_file)
            if not disk_path.exists():
                continue

            disk_content = disk_path.read_text(encoding="utf-8")
            cached = self.get_file_text(target_file)
            if cached == disk_content:
                continue

            self.set_file_text(
                target_file,
                disk_content,
                source="disk",
                patch_id=None,
            )
            changed.append(target_file)

        return changed

    def record_patch_apply(self, target_file, patch_id, content):
        self.set_file_text(
            target_file,
            content,
            source="applied_patch",
            patch_id=patch_id,
        )

    def record_patch_rollback(self, target_file, patch_id, content):
        self.set_file_text(
            target_file,
            content,
            source="rollback",
            patch_id=patch_id,
        )

    def get_file_history(self, target_file):
        history = self.patch_history.get(target_file, [])
        return copy.deepcopy(history)

    def get_last_patch_id(self, target_file):
        state = self.file_state.get(target_file)
        if not state:
            return None
        return state.get("last_patch_id")

    def clear_file_state(self, target_file):
        if target_file in self.file_state:
            del self.file_state[target_file]
        return True

    def set_task_state(self, task_id, data):
        self.task_state[task_id] = copy.deepcopy(data)
        return True

    def get_task_state(self, task_id):
        data = self.task_state.get(task_id)
        return copy.deepcopy(data) if data else None

    def set_agent_state(self, agent_name, data):
        self.agent_state[agent_name] = copy.deepcopy(data)
        return True

    def get_agent_state(self, agent_name):
        data = self.agent_state.get(agent_name)
        return copy.deepcopy(data) if data else None

    def get_observability_snapshot(self):
        return copy.deepcopy(self.observability)

    def update_observability_section(self, section, data):
        if section not in self.observability:
            raise ValueError(f"Unknown observability section: {section}")

        if not isinstance(data, dict):
            raise ValueError("Observability section update data must be a dictionary.")

        current = self.observability.get(section) or {}
        merged = {**current, **copy.deepcopy(data)}
        merged["updated_at"] = self._now()
        self.observability[section] = merged
        return copy.deepcopy(merged)

    def set_current_work(self, data):
        if not isinstance(data, dict):
            raise ValueError("Current work data must be a dictionary.")

        normalized = dict(data)
        cues = normalized.get("completion_cues")
        if cues is None:
            normalized["completion_cues"] = []
        elif isinstance(cues, list):
            normalized["completion_cues"] = [
                cue for cue in cues if isinstance(cue, str) and cue.strip()
            ]
        else:
            normalized["completion_cues"] = []

        return self.update_observability_section("current", normalized)

    def set_last_patch(self, data):
        if not isinstance(data, dict):
            raise ValueError("Last patch data must be a dictionary.")

        normalized = dict(data)
        if normalized.get("timestamp") is None:
            normalized["timestamp"] = self._now()
        return self.update_observability_section("last_patch", normalized)

    def record_failure(self, data, max_recent=5):
        if not isinstance(data, dict):
            raise ValueError("Failure data must be a dictionary.")

        failures = copy.deepcopy(self.observability.get("failures") or {})
        recent = list(failures.get("recent") or [])
        counts = dict(failures.get("counts_by_category") or {})

        entry = copy.deepcopy(data)
        category = entry.get("failure_category") or "unknown_failure"
        entry["failure_category"] = category
        entry["timestamp"] = entry.get("timestamp") or self._now()

        recent.insert(0, entry)
        recent = recent[:max_recent]
        counts[category] = counts.get(category, 0) + 1

        self.observability["failures"] = {
            "recent": recent,
            "counts_by_category": counts,
            "updated_at": self._now(),
        }
        return copy.deepcopy(self.observability["failures"])

    def set_lessons(self, lessons):
        if not isinstance(lessons, list):
            raise ValueError("Lessons data must be a list.")

        self.observability["lessons"] = {
            "recent": copy.deepcopy(lessons),
            "updated_at": self._now(),
        }
        return copy.deepcopy(self.observability["lessons"])

    def set_active_route(self, route_name):
        return self.update_observability_section(
            "system",
            {"active_route": route_name},
        )

    def to_dict(self):
        return {
            "repo_state": self.repo_state,
            "file_state": self.file_state,
            "patch_history": self.patch_history,
            "task_state": self.task_state,
            "agent_state": self.agent_state,
            "observability": self.observability,
        }

    def save_snapshot(self):
        self.snapshot_path.write_text(
            json.dumps(self.to_dict(), indent=2),
            encoding="utf-8"
        )
        return str(self.snapshot_path)

    def load_snapshot(self):
        if not self.snapshot_path.exists():
            return False

        data = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        self.file_state = data.get("file_state", {})
        self.patch_history = data.get("patch_history", {})
        self.task_state = data.get("task_state", {})
        self.agent_state = data.get("agent_state", {})
        self.repo_state = data.get("repo_state", {"repo_map": None,"updated_at": None,})
        self.observability = data.get("observability", self._build_default_observability_snapshot())
        self.sync_tracked_files_with_disk()
        return True
