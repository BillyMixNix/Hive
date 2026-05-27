"""
Overnight batch runner for Hive.

Feeds a sequence of plan/code commands to main.py via stdin so tasks
can be processed without manual input.

Usage:
    python autorun.py                        # uses default task list below
    python autorun.py 868 929                # process specific task IDs
    python autorun.py 2>&1 | tee autorun.log # save full output
"""

import subprocess
import sys
import datetime
import os

# --- Config -----------------------------------------------------------

# Tasks to process. Override via command-line: python autorun.py 123 456
DEFAULT_TASK_IDS = [868, 929]

# How many code-task passes per task (one pass = one child task / one patch attempt).
# Extra passes beyond the actual child count are harmless — main.py reports
# "no ready child task" and moves on.
CODE_PASSES_PER_TASK = 6

# -----------------------------------------------------------------------


def build_commands(task_ids: list[int], code_passes: int) -> list[str]:
    cmds = []
    for tid in task_ids:
        cmds.append(f"active task {tid}")
        cmds.append(f"plan task {tid}")
        for _ in range(code_passes):
            cmds.append(f"code task {tid}")
    cmds.append("quit")
    return cmds


def run(task_ids: list[int], code_passes: int) -> None:
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(os.path.dirname(__file__), f"autorun_{stamp}.log")

    cmds = build_commands(task_ids, code_passes)
    stdin_text = "\n".join(cmds) + "\n"

    print(f"[autorun] {datetime.datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"[autorun] Tasks : {task_ids}")
    print(f"[autorun] Commands : {len(cmds)}")
    print(f"[autorun] Log : {log_path}")
    print()

    with open(log_path, "w", encoding="utf-8") as log:
        log.write(f"[autorun] start={datetime.datetime.now().isoformat()}\n")
        log.write(f"[autorun] tasks={task_ids}  passes_per_task={code_passes}\n")
        log.write(f"[autorun] commands=\n")
        for c in cmds:
            log.write(f"  {c}\n")
        log.write("\n" + "=" * 70 + "\n\n")

        proc = subprocess.run(
            [sys.executable, "main.py"],
            input=stdin_text,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        log.write(proc.stdout or "")
        log.write(f"\n\n[autorun] exit_code={proc.returncode}\n")
        log.write(f"[autorun] end={datetime.datetime.now().isoformat()}\n")

    # Mirror tail of output to console
    lines = (proc.stdout or "").splitlines()
    tail = lines[-40:] if len(lines) > 40 else lines
    for line in tail:
        print(line)

    print()
    print(f"[autorun] Done — exit code {proc.returncode}")
    print(f"[autorun] Full log: {log_path}")


if __name__ == "__main__":
    ids = [int(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else DEFAULT_TASK_IDS
    run(ids, CODE_PASSES_PER_TASK)
