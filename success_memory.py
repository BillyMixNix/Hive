"""
Success-memory store — ExpeL-style win-signal archive.

Mirrors HiveLessonMemory but stores accepted patches (wins) instead of
failures.  Each entry holds both:
  - signal / trajectory_ref   (concrete: the specific run that worked)
  - abstract_insight          (abstract: the reusable rule)

ExpeL's finding: store both because action-heavy retrieval wants the
concrete trajectory while reasoning-heavy retrieval wants the rule.

Memory ops (ADD / UPVOTE / DOWNVOTE / EDIT / prune) keep the store
honest: a win is only worth keeping if it keeps predicting wins.

Storage: success_memory.jsonl (append-only JSONL, rewritten on EDIT ops)
"""

import datetime
import json
import uuid
from pathlib import Path


class SuccessMemory:
    def __init__(self, path="success_memory.jsonl", max_entries=500, prune_floor=0.1):
        self.path = Path(path)
        self.max_entries = max_entries
        self.prune_floor = prune_floor
        self._ensure_file()

    def _ensure_file(self):
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")

    def _now(self):
        return datetime.datetime.utcnow().isoformat() + "Z"

    # ------------------------------------------------------------------ ADD

    def add_win(self, signal, trajectory_ref, abstract_insight, weight=1.0, **extra):
        """
        ADD — record a new win signal.

        Args:
          signal           Short description of what worked (concrete).
          trajectory_ref   Link to the archive entry (e.g. "archive.jsonl:v_20260529_...").
          abstract_insight The reusable rule abstracted from this win.
          weight           Starting weight; reinforced/demoted over time.
          **extra          Any additional fields (target_file, delta, etc.).
        """
        entry = {
            "id": f"win_{uuid.uuid4().hex[:12]}",
            "signal": signal,
            "trajectory_ref": trajectory_ref,
            "abstract_insight": abstract_insight,
            "weight": round(float(weight), 4),
            "wins": 1,
            "losses": 0,
            "timestamp": self._now(),
            **extra,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        self._trim()
        return entry["id"]

    # ------------------------------------------------------------ UPVOTE / DOWNVOTE

    def upvote(self, win_id, delta=0.1):
        """
        UPVOTE — signal recurred and predicted a real win.
        Increases weight and win count.
        """
        entries = self._load_all()
        for e in entries:
            if e.get("id") == win_id:
                e["weight"] = round(float(e.get("weight", 1.0)) + delta, 4)
                e["wins"] = int(e.get("wins", 0)) + 1
        self._save_all(entries)

    def downvote(self, win_id, delta=0.1):
        """
        DOWNVOTE — signal was present but the patch got rejected.
        Decreases weight (floor 0) and increments loss count.
        """
        entries = self._load_all()
        for e in entries:
            if e.get("id") == win_id:
                e["weight"] = round(max(0.0, float(e.get("weight", 1.0)) - delta), 4)
                e["losses"] = int(e.get("losses", 0)) + 1
        self._save_all(entries)

    # ------------------------------------------------------------------ EDIT / MERGE

    def edit(self, win_id, **updates):
        """
        EDIT — update specific fields on an existing win entry.
        Protected fields (id, timestamp) are ignored.
        """
        entries = self._load_all()
        for e in entries:
            if e.get("id") == win_id:
                for k, v in updates.items():
                    if k not in ("id", "timestamp"):
                        e[k] = v
        self._save_all(entries)

    def merge(self, win_id_keep, win_id_drop):
        """
        MERGE — collapse two near-duplicate signals into one.
        Keeps win_id_keep, sums wins/losses/weight, removes win_id_drop.
        """
        entries = self._load_all()
        keep = next((e for e in entries if e.get("id") == win_id_keep), None)
        drop = next((e for e in entries if e.get("id") == win_id_drop), None)
        if keep is None or drop is None:
            return False
        keep["wins"] = int(keep.get("wins", 0)) + int(drop.get("wins", 0))
        keep["losses"] = int(keep.get("losses", 0)) + int(drop.get("losses", 0))
        keep["weight"] = round(
            (float(keep.get("weight", 1.0)) + float(drop.get("weight", 1.0))) / 2, 4
        )
        remaining = [e for e in entries if e.get("id") != win_id_drop]
        self._save_all(remaining)
        return True

    # ------------------------------------------------------------------ PRUNE

    def prune(self, floor=None):
        """
        PRUNE — remove entries whose weight has fallen below floor.
        Returns number of entries removed.
        """
        floor = floor if floor is not None else self.prune_floor
        entries = self._load_all()
        kept = [e for e in entries if float(e.get("weight", 1.0)) >= floor]
        removed = len(entries) - len(kept)
        if removed:
            self._save_all(kept)
        return removed

    # ------------------------------------------------------------------ RETRIEVAL

    def find_relevant(self, context, limit=5):
        """
        Return the most relevant wins for a given context dict.
        Scores by weight + target_file match in the signal text.
        """
        entries = self._load_all()
        target_file = context.get("target_file", "")
        scored = []
        for e in entries:
            score = float(e.get("weight", 1.0))
            if target_file and target_file in e.get("signal", ""):
                score += 2.0
            if target_file and target_file in e.get("abstract_insight", ""):
                score += 1.0
            scored.append((score, e))
        scored.sort(key=lambda x: -x[0])
        return [e for _, e in scored[:limit]]

    def get_recent(self, limit=10):
        """Return the most recently added win entries."""
        return self._load_all()[-limit:]

    def get_all(self):
        return self._load_all()

    # ------------------------------------------------------------------ INTERNAL

    def _load_all(self):
        if not self.path.exists():
            return []
        entries = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return entries

    def _save_all(self, entries):
        with self.path.open("w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

    def _trim(self):
        entries = self._load_all()
        if len(entries) > self.max_entries:
            self._save_all(entries[-self.max_entries:])
