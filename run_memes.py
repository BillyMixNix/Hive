"""
Batch meme runner: processes a directory of meme images (with optional captions),
feeds them through agents, runs reasoning heads, and logs router decisions.

Usage:
    python run_memes.py --memes-dir ./memes --output results/memes.jsonl --device cpu

Optional:
    --metadata path/to/meta.jsonl   # lines with {"path": "...", "caption": "...", "timestamp": ...}
    --limit 500                     # cap number of memes
"""

import argparse
import json
import os
import time
from pathlib import Path
from typing import Dict, Optional

import torch
from PIL import Image

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None

from HiveBridge import HiveBridge
from HiveMain import HiveMain
from HiveMemoryAgent import MemoryAgent
from HiveLanguageAgent import LanguageAgent
from HiveVisionAgent import VisionAgent
from HiveReasoningHeads import (
    NoveltyHead,
    CoherenceHead,
    AmbiguityHead,
    ConsistencyHead,
    TemporalFitHead,
)
from HiveRouter import HiveRouter


def load_metadata(meta_path: Optional[str]) -> Dict[str, Dict]:
    if not meta_path:
        return {}
    meta = {}
    with open(meta_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            path = obj.get("path")
            if path:
                meta[path] = obj
    return meta


def iter_memes(meme_dir: Path, limit: Optional[int] = None):
    exts = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
    count = 0
    for path in meme_dir.rglob("*"):
        if path.suffix.lower() in exts and path.is_file():
            yield path
            count += 1
            if limit and count >= limit:
                break


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--memes-dir", help="Directory containing meme images")
    parser.add_argument("--metadata", help="Optional JSONL with path, caption, timestamp")
    parser.add_argument("--output", default="results/memes.jsonl", help="JSONL output file")
    parser.add_argument("--device", default="cpu", help="cpu or cuda")
    parser.add_argument("--limit", type=int, help="Limit number of memes processed")
    parser.add_argument("--gui", action="store_true", help="Launch a simple GUI to choose paths")
    args = parser.parse_args()

    if args.gui or not args.memes_dir:
        gui_args = launch_gui(
            default_output=args.output,
            default_device=args.device,
        )
        if gui_args is None:
            print("[runner] GUI cancelled.")
            return
        args.memes_dir = gui_args["memes_dir"]
        args.metadata = gui_args["metadata"]
        args.output = gui_args["output"]
        args.device = gui_args["device"]
        args.limit = gui_args["limit"]

    device = torch.device(args.device)
    meme_dir = Path(args.memes_dir)
    meme_dir.mkdir(parents=True, exist_ok=True)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)

    metadata = load_metadata(args.metadata)

    # Initialize agents
    language_agent = LanguageAgent(device=device)
    vision_agent = VisionAgent(device=device)
    memory_agent = MemoryAgent(device=device)
    bridge = HiveBridge()

    # Reasoning heads and router
    heads = [
        NoveltyHead(current_key="current_vector", memory_key="memory_vectors"),
        CoherenceHead(agent_key="agent_vectors"),
        ConsistencyHead(agent_key="agent_vectors"),
        AmbiguityHead(probs_key="candidate_probs"),
        TemporalFitHead(timestamp_key="timestamp", reference_key="reference_time", tolerance_seconds=3600),
    ]
    router = HiveRouter(min_confidence=0.2, disagreement_brake=0.35)

    hive = HiveMain(
        agents=[language_agent, vision_agent, memory_agent],
        bridge=bridge,
        reasoning_heads=heads,
        router=router,
    )

    meme_paths = list(iter_memes(meme_dir, args.limit))
    iterator = tqdm(meme_paths, desc="Memes") if tqdm else meme_paths

    with open(args.output, "w", encoding="utf-8") as out_f:
        for path in iterator:
            meta = metadata.get(str(path), {})
            caption = meta.get("caption") or path.stem
            ts = meta.get("timestamp") or time.time()

            try:
                image = Image.open(path).convert("RGB")
            except Exception as e:
                print(f"[runner] Failed to load {path}: {e}")
                continue

            input_data = {
                language_agent.name: caption,
                vision_agent.name: image,
                "timestamp": ts,
            }

            hive.step(input_data)

            # Log opinions and decision
            record = {
                "path": str(path),
                "caption": caption,
                "timestamp": ts,
                "opinions": [
                    {"name": op.name, "score": op.score, "confidence": op.confidence}
                    for op in hive.last_opinions
                ],
                "decision": {
                    "abstain": hive.last_decision.abstain if hive.last_decision else True,
                    "score": hive.last_decision.score if hive.last_decision else None,
                    "confidence": hive.last_decision.confidence if hive.last_decision else None,
                    "source": hive.last_decision.source if hive.last_decision else None,
                    "reason": hive.last_decision.reason if hive.last_decision else "no_decision",
                },
            }
            out_f.write(json.dumps(record) + "\n")
            out_f.flush()

    if tqdm:
        iterator.close()


def launch_gui(default_output: str, default_device: str):
    """
    Minimal Tkinter GUI to choose meme dir, metadata file, output file, device, and limit.
    Returns a dict matching argparse fields or None if cancelled.
    """
    import tkinter as tk
    from tkinter import filedialog, simpledialog

    root = tk.Tk()
    root.title("Hive Meme Runner")
    root.geometry("520x240")
    root.resizable(False, False)

    state = {
        "memes_dir": tk.StringVar(value=""),
        "metadata": tk.StringVar(value=""),
        "output": tk.StringVar(value=default_output),
        "device": tk.StringVar(value=default_device),
        "limit": tk.StringVar(value=""),
    }

    def browse_dir():
        path = filedialog.askdirectory(title="Select memes directory")
        if path:
            state["memes_dir"].set(path)

    def browse_meta():
        path = filedialog.askopenfilename(
            title="Select metadata JSONL (optional)",
            filetypes=[("JSONL files", "*.jsonl"), ("All files", "*.*")],
        )
        if path:
            state["metadata"].set(path)

    def browse_output():
        path = filedialog.asksaveasfilename(
            title="Select output JSONL",
            defaultextension=".jsonl",
            filetypes=[("JSONL files", "*.jsonl"), ("All files", "*.*")],
        )
        if path:
            state["output"].set(path)

    def submit():
        if not state["memes_dir"].get():
            tk.messagebox.showerror("Missing memes dir", "Please select a memes directory.")
            return
        root.quit()

    row = 0
    for label, key, browse_fn in [
        ("Memes dir", "memes_dir", browse_dir),
        ("Metadata (optional)", "metadata", browse_meta),
        ("Output JSONL", "output", browse_output),
    ]:
        tk.Label(root, text=label, anchor="w", width=18).grid(row=row, column=0, padx=8, pady=8, sticky="w")
        tk.Entry(root, textvariable=state[key], width=48).grid(row=row, column=1, padx=4, pady=4)
        tk.Button(root, text="Browse", command=browse_fn, width=8).grid(row=row, column=2, padx=4, pady=4)
        row += 1

    tk.Label(root, text="Device (cpu/cuda)", anchor="w", width=18).grid(row=row, column=0, padx=8, pady=8, sticky="w")
    tk.Entry(root, textvariable=state["device"], width=16).grid(row=row, column=1, padx=4, pady=4, sticky="w")
    row += 1

    tk.Label(root, text="Limit (optional)", anchor="w", width=18).grid(row=row, column=0, padx=8, pady=8, sticky="w")
    tk.Entry(root, textvariable=state["limit"], width=16).grid(row=row, column=1, padx=4, pady=4, sticky="w")
    row += 1

    tk.Button(root, text="Run", command=submit, width=10).grid(row=row, column=1, pady=12)
    tk.Button(root, text="Cancel", command=root.destroy, width=10).grid(row=row, column=2, pady=12)

    root.mainloop()

    if not state["memes_dir"].get():
        return None

    try:
        limit_val = int(state["limit"].get()) if state["limit"].get() else None
    except ValueError:
        limit_val = None

    return {
        "memes_dir": state["memes_dir"].get(),
        "metadata": state["metadata"].get() or None,
        "output": state["output"].get(),
        "device": state["device"].get() or "cpu",
        "limit": limit_val,
    }


if __name__ == "__main__":
    main()
