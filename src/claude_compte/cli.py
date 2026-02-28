"""CLI entry point for claude-compte."""

import argparse
import sys
import threading
import webbrowser
from claude_compte.server import create_app


def main():
    parser = argparse.ArgumentParser(
        prog="claude-compte",
        description="Token usage analytics dashboard for Claude Code",
    )
    parser.add_argument("--port", type=int, default=3456, help="Port to serve on (default: 3456)")
    parser.add_argument("--no-open", action="store_true", help="Don't open the browser automatically")
    args = parser.parse_args()

    app = create_app()

    if not args.no_open:
        threading.Timer(1.0, webbrowser.open, args=[f"http://localhost:{args.port}"]).start()

    try:
        import uvicorn
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    except OSError as e:
        if "address already in use" in str(e).lower() or "errno 48" in str(e).lower():
            print(f"Error: port {args.port} is already in use. Try --port <other>", file=sys.stderr)
            sys.exit(1)
        raise
