import queue
import subprocess
import sys
import threading
import tkinter as tk
import json
import re
from pathlib import Path
from tkinter import messagebox, ttk


ROOT = Path(__file__).resolve().parent


class HiveGui(tk.Tk):
    QUICK_COMMANDS = (
        ("Cockpit", "show cockpit"),
        ("Current", "show current"),
        ("Memory", "memory"),
        ("Lessons", "show lessons"),
        ("Failures", "show failures"),
        ("Pending Reviews", "pending patch reviews"),
        ("Pending Recoveries", "pending recoveries"),
        ("Code Status", "code status"),
        ("Math Status", "math status"),
        ("Help", "help"),
    )

    def __init__(self):
        super().__init__()
        self.title("Hive")
        self.geometry("1080x720")
        self.minsize(860, 560)

        self.proc = None
        self.output_queue = queue.Queue()
        self.reader_thread = None
        self.running = False

        self.task_id = tk.StringVar()
        self.patch_id = tk.StringVar()
        self.command_text = tk.StringVar()
        self.status_text = tk.StringVar(value="Offline")
        self.last_created_task_id = tk.StringVar(value="")

        self._build_ui()
        self._start_hive()
        self._refresh_tasks()
        self.after(80, self._drain_output)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        top = ttk.Frame(self, padding=(12, 10))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="Hive", font=("Segoe UI", 16, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(top, textvariable=self.status_text).grid(row=0, column=1, sticky="w", padx=(12, 0))
        ttk.Button(top, text="Restart", command=self._restart_hive).grid(row=0, column=2, sticky="e")

        body = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        body.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

        left = ttk.Frame(body, padding=(0, 0, 10, 0))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(6, weight=1)
        body.add(left, weight=0)

        ttk.Label(left, text="New Task", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w")
        new_task = ttk.Frame(left)
        new_task.grid(row=1, column=0, sticky="ew", pady=(8, 14))
        new_task.columnconfigure(0, weight=1)
        self.task_description = tk.Text(new_task, height=5, wrap="word", font=("Segoe UI", 10))
        self.task_description.grid(row=0, column=0, columnspan=3, sticky="ew")
        ttk.Button(new_task, text="Create", command=self._create_task).grid(row=1, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(new_task, text="Create + Plan", command=self._create_and_plan_task).grid(
            row=1, column=1, sticky="ew", padx=6, pady=(6, 0)
        )
        ttk.Button(new_task, text="Refresh", command=self._refresh_tasks).grid(row=1, column=2, sticky="ew", pady=(6, 0))

        ttk.Label(left, text="Quick Actions", font=("Segoe UI", 10, "bold")).grid(row=2, column=0, sticky="w")
        quick = ttk.Frame(left)
        quick.grid(row=3, column=0, sticky="ew", pady=(8, 14))
        quick.columnconfigure(0, weight=1)
        quick.columnconfigure(1, weight=1)

        for index, (label, command) in enumerate(self.QUICK_COMMANDS):
            button = ttk.Button(quick, text=label, command=lambda value=command: self._send(value))
            button.grid(row=index // 2, column=index % 2, sticky="ew", padx=3, pady=3)

        forms = ttk.Notebook(left)
        forms.grid(row=4, column=0, sticky="ew")

        task_tab = ttk.Frame(forms, padding=8)
        patch_tab = ttk.Frame(forms, padding=8)
        research_tab = ttk.Frame(forms, padding=8)
        forms.add(task_tab, text="Tasks")
        forms.add(patch_tab, text="Patches")
        forms.add(research_tab, text="Research")

        self._build_task_tab(task_tab)
        self._build_patch_tab(patch_tab)
        self._build_research_tab(research_tab)

        ttk.Label(left, text="Recent Tasks", font=("Segoe UI", 10, "bold")).grid(row=5, column=0, sticky="sw", pady=(14, 0))
        task_list = ttk.Frame(left)
        task_list.grid(row=6, column=0, sticky="nsew", pady=(8, 0))
        task_list.columnconfigure(0, weight=1)
        task_list.rowconfigure(0, weight=1)
        self.tasks = ttk.Treeview(task_list, columns=("status", "note"), show="headings", height=7)
        self.tasks.heading("status", text="Status")
        self.tasks.heading("note", text="Task")
        self.tasks.column("status", width=90, stretch=False)
        self.tasks.column("note", width=260, stretch=True)
        self.tasks.grid(row=0, column=0, sticky="nsew")
        task_scroll = ttk.Scrollbar(task_list, orient=tk.VERTICAL, command=self.tasks.yview)
        task_scroll.grid(row=0, column=1, sticky="ns")
        self.tasks.configure(yscrollcommand=task_scroll.set)
        self.tasks.bind("<<TreeviewSelect>>", self._select_task)

        ttk.Label(left, text="Command", font=("Segoe UI", 10, "bold")).grid(row=7, column=0, sticky="sw", pady=(14, 0))
        command_box = ttk.Frame(left)
        command_box.grid(row=8, column=0, sticky="ew", pady=(8, 0))
        command_box.columnconfigure(0, weight=1)
        entry = ttk.Entry(command_box, textvariable=self.command_text)
        entry.grid(row=0, column=0, sticky="ew")
        entry.bind("<Return>", lambda _event: self._send_command_entry())
        ttk.Button(command_box, text="Send", command=self._send_command_entry).grid(row=0, column=1, padx=(6, 0))

        right = ttk.Frame(body)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        body.add(right, weight=1)

        toolbar = ttk.Frame(right)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(toolbar, text="Transcript", font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Clear", command=self._clear_transcript).pack(side=tk.RIGHT)

        transcript_frame = ttk.Frame(right)
        transcript_frame.grid(row=1, column=0, sticky="nsew")
        transcript_frame.columnconfigure(0, weight=1)
        transcript_frame.rowconfigure(0, weight=1)

        self.transcript = tk.Text(
            transcript_frame,
            wrap="word",
            state="disabled",
            font=("Consolas", 10),
            padx=10,
            pady=10,
        )
        self.transcript.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(transcript_frame, orient=tk.VERTICAL, command=self.transcript.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.transcript.configure(yscrollcommand=scroll.set)

    def _build_task_tab(self, parent):
        parent.columnconfigure(1, weight=1)
        ttk.Label(parent, text="Task ID").grid(row=0, column=0, sticky="w")
        ttk.Entry(parent, textvariable=self.task_id, width=10).grid(row=0, column=1, sticky="ew", padx=(6, 0))
        ttk.Label(parent, textvariable=self.last_created_task_id).grid(row=1, column=0, columnspan=2, sticky="w", pady=(5, 0))

        actions = (
            ("Show", "show task {id}"),
            ("Plan", "plan task {id}"),
            ("Code", "code task {id}"),
            ("Continue", "continue task {id}"),
            ("Complete", "complete task {id}"),
            ("Set Active", "active task {id}"),
        )
        for index, (label, template) in enumerate(actions, start=2):
            ttk.Button(parent, text=label, command=lambda t=template: self._send_task(t)).grid(
                row=index, column=0, columnspan=2, sticky="ew", pady=3
            )

    def _build_patch_tab(self, parent):
        parent.columnconfigure(1, weight=1)
        ttk.Label(parent, text="Patch ID").grid(row=0, column=0, sticky="w")
        ttk.Entry(parent, textvariable=self.patch_id, width=10).grid(row=0, column=1, sticky="ew", padx=(6, 0))

        actions = (
            ("Show", "show patch {id}"),
            ("Review", "review patch {id}"),
            ("Accept Pilot Review", "pilot accept patch {id}"),
            ("Approve", "approve patch {id}"),
            ("Apply", "apply patch {id}"),
            ("Verify", "verify patch {id}"),
            ("Rollback", "rollback patch {id}"),
        )
        for index, (label, template) in enumerate(actions, start=1):
            ttk.Button(parent, text=label, command=lambda t=template: self._send_patch(t)).grid(
                row=index, column=0, columnspan=2, sticky="ew", pady=3
            )

    def _build_research_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        commands = (
            ("Scan Current Repo", "scan ."),
            ("Show Code Lessons", "show code lessons"),
            ("Show Hypotheses", "show hypotheses"),
            ("Show Math Lessons", "show math lessons"),
            ("Show Conjectures", "show conjectures"),
        )
        for index, (label, command) in enumerate(commands):
            ttk.Button(parent, text=label, command=lambda value=command: self._send(value)).grid(
                row=index, column=0, sticky="ew", pady=3
            )

    def _start_hive(self):
        if self.proc and self.proc.poll() is None:
            return

        self._append_system("Starting Hive...")
        self.status_text.set("Starting")
        self.proc = subprocess.Popen(
            [sys.executable, "-u", str(ROOT / "main.py")],
            cwd=str(ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self.running = True
        self.reader_thread = threading.Thread(target=self._read_output, daemon=True)
        self.reader_thread.start()
        self.status_text.set("Online")

    def _restart_hive(self):
        self._stop_hive()
        self._start_hive()

    def _stop_hive(self):
        self.running = False
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.status_text.set("Offline")

    def _read_output(self):
        if not self.proc or not self.proc.stdout:
            return
        while True:
            chunk = self.proc.stdout.read(1)
            if not chunk:
                break
            self.output_queue.put(chunk)
        self.output_queue.put("\n[Hive process ended]\n")

    def _drain_output(self):
        try:
            while True:
                self._append_text(self.output_queue.get_nowait())
        except queue.Empty:
            pass

        if self.proc and self.proc.poll() is not None:
            self.status_text.set("Offline")

        self.after(80, self._drain_output)

    def _send_command_entry(self):
        command = self.command_text.get().strip()
        if not command:
            return
        self.command_text.set("")
        self._send(command)

    def _create_task(self):
        description = self.task_description.get("1.0", tk.END).strip()
        if not description:
            messagebox.showinfo("Task description required", "Describe what Hive should do first.")
            return
        before = self._latest_task_id()
        self._send(description)
        self.task_description.delete("1.0", tk.END)
        self.after(1200, lambda: self._capture_created_task(before, plan_after=False))

    def _create_and_plan_task(self):
        description = self.task_description.get("1.0", tk.END).strip()
        if not description:
            messagebox.showinfo("Task description required", "Describe what Hive should do first.")
            return
        before = self._latest_task_id()
        self._send(description)
        self.task_description.delete("1.0", tk.END)
        self.after(1600, lambda: self._capture_created_task(before, plan_after=True))

    def _capture_created_task(self, previous_id, plan_after=False):
        self._refresh_tasks()
        latest_id = self._latest_task_id()
        if latest_id is None or latest_id == previous_id:
            self.last_created_task_id.set("Task created; refresh if it is not listed yet.")
            return
        self.task_id.set(str(latest_id))
        self.last_created_task_id.set(f"Selected task {latest_id}")
        if plan_after:
            self._send(f"plan task {latest_id}")

    def _send_task(self, template):
        task_id = self.task_id.get().strip()
        if not task_id.isdigit():
            messagebox.showinfo("Task ID required", "Enter a numeric task ID first.")
            return
        self._send(template.format(id=task_id))

    def _send_patch(self, template):
        patch_id = self.patch_id.get().strip()
        if not patch_id.isdigit():
            messagebox.showinfo("Patch ID required", "Enter a numeric patch ID first.")
            return
        self._send(template.format(id=patch_id))

    def _refresh_tasks(self):
        if not hasattr(self, "tasks"):
            return
        for item in self.tasks.get_children():
            self.tasks.delete(item)
        for entry in self._load_recent_tasks():
            note = self._shorten(entry.get("note") or entry.get("tag") or "", 86)
            status = entry.get("status") or ""
            entry_id = str(entry.get("id"))
            self.tasks.insert("", tk.END, iid=entry_id, values=(status, note))

    def _select_task(self, _event=None):
        selected = self.tasks.selection()
        if selected:
            self.task_id.set(selected[0])

    def _load_recent_tasks(self):
        memory_path = ROOT / "hive_memory.json"
        if not memory_path.exists():
            return []
        try:
            entries = json.loads(memory_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        task_entries = [
            entry for entry in entries
            if isinstance(entry, dict) and self._looks_like_task(entry)
        ]
        return task_entries[-30:][::-1]

    def _looks_like_task(self, entry):
        tag = str(entry.get("tag") or "").lower()
        metadata = entry.get("metadata") or {}
        if tag == "builder" or tag == "continued_task":
            return True
        if isinstance(metadata, dict) and ("builder_result" in metadata or "plan" in metadata):
            return True
        return False

    def _latest_task_id(self):
        tasks = self._load_recent_tasks()
        if not tasks:
            return None
        try:
            return int(tasks[0].get("id"))
        except (TypeError, ValueError):
            return None

    def _shorten(self, text, limit):
        clean = re.sub(r"\s+", " ", str(text)).strip()
        if len(clean) <= limit:
            return clean
        return clean[: limit - 3] + "..."

    def _send(self, command):
        if not self.proc or self.proc.poll() is not None:
            self._start_hive()
        if not self.proc or not self.proc.stdin:
            messagebox.showerror("Hive is offline", "Hive could not be started.")
            return

        self._append_user(command)
        try:
            self.proc.stdin.write(command + "\n")
            self.proc.stdin.flush()
        except BrokenPipeError:
            self.status_text.set("Offline")
            messagebox.showerror("Hive is offline", "Hive stopped before the command could be sent.")

    def _append_user(self, text):
        self._append_text(f"\nPilot > {text}\n")

    def _append_system(self, text):
        self._append_text(f"[{text}]\n")

    def _append_text(self, text):
        self.transcript.configure(state="normal")
        self.transcript.insert(tk.END, text)
        self.transcript.see(tk.END)
        self.transcript.configure(state="disabled")

    def _clear_transcript(self):
        self.transcript.configure(state="normal")
        self.transcript.delete("1.0", tk.END)
        self.transcript.configure(state="disabled")

    def _on_close(self):
        self._stop_hive()
        self.destroy()


if __name__ == "__main__":
    HiveGui().mainloop()
