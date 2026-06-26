#!/usr/bin/env python3
"""Print a summary of trusted Hive lessons for injection into session context."""
import json
from pathlib import Path


def load_lessons(path):
    lessons = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                lessons.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return lessons


def success_score(lesson):
    times = lesson.get("times_used") or 0
    successes = lesson.get("success_after_use") or 0
    rate = successes / times if times > 0 else 0.0
    return (rate, times, lesson.get("confidence") or 0.0)


def format_lessons(lessons):
    trusted = [l for l in lessons if l.get("promotion_state") == "trusted"]
    top = sorted(trusted, key=success_score, reverse=True)[:12]

    lines = []
    lines.append("=== Hive Lessons ===")
    lines.append(f"{len(lessons)} total | {len(trusted)} trusted | showing top {len(top)}")
    lines.append("")

    for l in top:
        family = l.get("failure_family") or "unknown"
        code = l.get("failure_code") or ""
        pattern = (l.get("failure_pattern") or "").strip()
        instruction = (l.get("retry_instruction") or "").strip()
        times = l.get("times_used") or 0
        successes = l.get("success_after_use") or 0
        label = f"[{family}/{code}]" if code else f"[{family}]"
        rate = f"{successes}/{times}" if times else "?"

        why = (l.get("why") or "").strip()
        lines.append(f"{label} ({rate} success)")
        if pattern:
            lines.append(f"  When:  {pattern}")
        if why:
            lines.append(f"  Why:   {why}")
        if instruction:
            lines.append(f"  Do:    {instruction}")
        lines.append("")

    lines.append("=== End Hive Lessons ===")
    return "\n".join(lines)


def main():
    repo_root = Path(__file__).parent.parent
    lessons_path = repo_root / "hive_lessons.jsonl"

    if not lessons_path.exists():
        print("hive_lessons.jsonl not found — skipping lesson load.")
        return

    lessons = load_lessons(lessons_path)
    if not lessons:
        print("hive_lessons.jsonl is empty.")
        return

    print(format_lessons(lessons))


if __name__ == "__main__":
    main()
