"""
Hive Conversational Interface — parallel entry point to main.py.

Natural language dialogue between the Pilot and Hive, powered by a
local Ollama model. The existing main.py CLI is unchanged.

Usage:
    python HiveConverse.py
    python HiveConverse.py --model qwen2.5:14b
"""

import sys
import textwrap


def _print_response(text: str):
    """Print Hive's response with consistent formatting."""
    print()
    lines = text.split("\n")
    wrapped = []
    for line in lines:
        if len(line) > 80 and not line.startswith(" "):
            wrapped.append(textwrap.fill(line, width=80))
        else:
            wrapped.append(line)
    formatted = "\n      ".join("\n".join(wrapped).split("\n"))
    print(f"Hive: {formatted}")
    print()


def _print_banner(model: str, project_dir: str = None):
    print("=" * 60)
    print("  Hive Conversational Interface")
    print(f"  Model: {model}")
    if project_dir:
        print(f"  Project: {project_dir}")
    print("  Type 'exit' or press Ctrl+C to end the session.")
    print("=" * 60)
    print()


def main():
    model = None
    project_dir = None
    args = sys.argv[1:]

    if "--model" in args:
        idx = args.index("--model")
        if idx + 1 < len(args):
            model = args[idx + 1]

    if "--project" in args:
        idx = args.index("--project")
        if idx + 1 < len(args):
            project_dir = args[idx + 1]

    from conversation_manager import ConversationManager, DEFAULT_MODEL

    resolved_model = model or DEFAULT_MODEL
    _print_banner(resolved_model, project_dir=project_dir)

    try:
        manager = ConversationManager(model=resolved_model, project_dir=project_dir)
    except Exception as exc:
        print(f"Failed to initialize Hive: {exc}")
        sys.exit(1)

    print("Hive: Online. State loaded. Ready.")
    print()

    while True:
        try:
            raw = input("Pilot: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nHive: Session ended.")
            break

        if not raw:
            continue

        if raw.lower() in ("exit", "quit", "bye", "disconnect"):
            print("Hive: Understood. Signing off.")
            break

        try:
            response = manager.chat(raw)
        except RuntimeError as exc:
            print(f"\nHive: {exc}\n")
            continue
        except KeyboardInterrupt:
            print("\n[interrupted]")
            continue

        _print_response(response)


if __name__ == "__main__":
    main()
