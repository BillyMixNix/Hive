import argparse
import json

from jarvis.store import Store
from .adapter import OllamaHive
from .loop import run


def main():
    parser = argparse.ArgumentParser(description="Hive learning development loop")
    commands = parser.add_subparsers(dest="command", required=True)
    learn = commands.add_parser("run")
    learn.add_argument("--data", required=True)
    learn.add_argument("--task", required=True)
    learn.add_argument("--suite", required=True)
    learn.add_argument("--suite-sha256", required=True)
    learn.add_argument("--model", required=True)
    learn.add_argument("--provider", choices=("ollama", "openai"), default="ollama")
    learn.add_argument("--url", help="Ollama chat endpoint only")
    learn.add_argument("--env-file", help="explicit private env file containing an already provisioned OpenAI key")
    learn.add_argument("--max-requests", type=int, help="required for OpenAI; total episode request limit")
    learn.add_argument("--max-output-tokens", type=int, help="OpenAI output limit per request (default 4096)")
    learn.add_argument("--calls", type=int, choices=(36,), default=36)
    learn.add_argument("--seed", type=int, default=42)
    commands.add_parser("demo")
    retirement = commands.add_parser("retire")
    retirement.add_argument("--data", required=True)
    retirement.add_argument("--episode", required=True)
    retirement.add_argument("--reason", required=True)
    args = parser.parse_args()
    if args.command == "demo":
        from .demo import main as demo
        return demo()
    if args.command == "retire":
        from .ledger import retire
        event = retire(Store(args.data), args.episode, args.reason)
        print(json.dumps({"retired": args.episode, "event": event}))
        return 0
    if args.provider == "openai":
        if args.url or args.max_requests is None:
            parser.error("OpenAI requires --max-requests and uses a fixed endpoint; omit --url")
        from .openai_adapter import OpenAIHive, load_api_key
        try:
            adapter = OpenAIHive(args.model, load_api_key(args.env_file),
                                 max_requests=args.max_requests,
                                 max_output_tokens=args.max_output_tokens if args.max_output_tokens is not None else 4096,
                                 seed=args.seed)
        except ValueError as exc:
            parser.error(str(exc))
    else:
        if any(value is not None for value in (args.env_file, args.max_requests, args.max_output_tokens)):
            parser.error("--env-file, --max-requests and --max-output-tokens require --provider openai")
        adapter = OllamaHive(args.model, args.url or "http://localhost:11434/api/chat", args.seed)
    report = run(Store(args.data), args.task, args.suite, args.suite_sha256,
                 adapter, calls=args.calls, seed=args.seed)
    print(json.dumps(report, indent=2))
    return 0 if report["verdict"] == "PROMOTED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
