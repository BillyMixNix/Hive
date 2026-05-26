"""
Hive Conversational Interface — parallel entry point to main.py.

Natural language dialogue between the Pilot and Hive.
The existing main.py CLI is unchanged.

Usage:
    python HiveConverse.py
"""

import os
import sys
import textwrap


def _check_api_key():
    """Warn if no obvious API credential is available."""
    has_key = (
        os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        or os.environ.get("ANTHROPIC_PROFILE")
    )
    if not has_key:
        print("Warning: ANTHROPIC_API_KEY is not set.")
        print("Set it with: export ANTHROPIC_API_KEY=<your-key>")
        print("Continuing — will fail on first message if no other auth is configured.")
        print()


def _print_response(text: str):
    """Print Hive's response with consistent formatting."""
    print()
    # Wrap long lines at 80 chars but preserve intentional line breaks
    lines = text.split("\n")
    wrapped = []
    for line in lines:
        if len(line) > 80 and not line.startswith(" "):
            wrapped.append(textwrap.fill(line, width=80))
        else:
            wrapped.append(line)
    print("Hive: " + "\n      ".join("\n".join(wrapped).split("\n")))
    print()


def _print_banner():
    print("=" * 60)
    print("  Hive Conversational Interface")
    print("  Type 'exit' or press Ctrl+C to end the session.")
    print("=" * 60)
    print()


def main():
    _check_api_key()

    from conversation_manager import ConversationManager

    _print_banner()

    try:
        manager = ConversationManager()
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
        except KeyboardInterrupt:
            print("\n[interrupted]")
            continue
        except Exception as exc:
            print(f"\nHive: Error — {exc}\n")
            continue

        _print_response(response)


if __name__ == "__main__":
    main()
