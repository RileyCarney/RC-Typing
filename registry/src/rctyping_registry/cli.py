"""Command-line interface for rctyping-registry."""

import argparse
import uvicorn
from rctyping_registry.config import registry_settings


def cmd_serve(args: argparse.Namespace) -> None:
    host = args.host or registry_settings.host
    port = args.port or registry_settings.port
    print(f"Starting rc-typing registry server at http://{host}:{port}")
    uvicorn.run("rctyping_registry.main:app", host=host, port=port, reload=args.reload)


def main() -> None:
    parser = argparse.ArgumentParser(prog="rctyping-registry", description="rc-typing Registry CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_serve = subparsers.add_parser("serve", help="Start Registry web server")
    p_serve.add_argument("--host", default=None, help="Host to bind to")
    p_serve.add_argument("--port", type=int, default=None, help="Port to listen on")
    p_serve.add_argument("--reload", action="store_true", help="Enable auto-reload")
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
