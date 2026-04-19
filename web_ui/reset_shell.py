#!/usr/bin/env python3
"""Interactive shell for sending /reset (and a few adjacent) requests to a
running skyrl_server.

Usage:
    python3 reset_shell.py                       # localhost:5000
    python3 reset_shell.py --port 5020
    python3 reset_shell.py --host 202.78.161.193 --port 5022
    python3 reset_shell.py --url http://10.0.0.5:5000

At the prompt:
    reset                         # reset with no options
    reset 3                       # shortcut: task_id=3
    reset task_id=3 mode=test     # key=value tokens populate options{}
    reset seed=42 task_id=7       # seed is top-level; others go into options
    health                        # GET /health
    deep_health                   # GET /deep_health
    help                          # show this help
    quit                          # exit (also: exit, q, Ctrl-D)
"""

import argparse
import json
import sys

try:
    import requests
except ImportError:
    print("error: 'requests' is required. Install with: pip install requests", file=sys.stderr)
    sys.exit(1)


RESET_TOP_LEVEL = {"seed"}  # everything else becomes part of options{}
DEFAULT_TIMEOUT = 600       # reset can restart the emulator; be generous


def parse_value(raw: str):
    """Coerce key=value strings to int/float/bool/None where obvious."""
    if raw.lower() in ("true", "false"):
        return raw.lower() == "true"
    if raw.lower() in ("none", "null"):
        return None
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def parse_tokens(tokens):
    """Turn [`3`, `mode=test`, `seed=42`] into (seed, options)."""
    seed = None
    options = {}
    for i, tok in enumerate(tokens):
        if "=" in tok:
            key, _, raw = tok.partition("=")
            key = key.strip()
            val = parse_value(raw.strip())
            if key in RESET_TOP_LEVEL:
                if key == "seed":
                    seed = val
            else:
                options[key] = val
        elif i == 0:
            # first bare positional arg is a task_id shortcut
            options["task_id"] = parse_value(tok)
        else:
            raise ValueError(f"unexpected token {tok!r}; use key=value form")
    return seed, options


def summarize_response(data):
    """Strip/abbreviate the huge base64 image field for readable output."""
    if not isinstance(data, dict):
        return data
    out = dict(data)
    obs = out.get("observation")
    if isinstance(obs, dict):
        obs = dict(obs)
        img = obs.get("image")
        if isinstance(img, str):
            obs["image"] = f"<base64 image, {len(img)} chars>"
        out["observation"] = obs
    info = out.get("info")
    if isinstance(info, dict) and "ui_elements" in info:
        elems = info["ui_elements"]
        if isinstance(elems, list):
            info = dict(info)
            info["ui_elements"] = f"<{len(elems)} ui elements>"
            out["info"] = info
    return out


def post(url: str, path: str, payload: dict, timeout: float):
    r = requests.post(f"{url}{path}", json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


def get(url: str, path: str, timeout: float):
    r = requests.get(f"{url}{path}", timeout=timeout)
    r.raise_for_status()
    return r.json()


def run_command(url: str, line: str, timeout: float) -> bool:
    """Execute one command line. Return False to exit the shell."""
    parts = line.strip().split()
    if not parts:
        return True
    cmd, args = parts[0].lower(), parts[1:]

    if cmd in ("exit", "quit", "q"):
        return False
    if cmd in ("help", "?", "h?"):
        print(__doc__)
        return True
    if cmd in ("reset", "r"):
        try:
            seed, options = parse_tokens(args)
        except ValueError as e:
            print(f"  parse error: {e}")
            return True
        payload = {"seed": seed, "options": options or None}
        print(f"  POST /reset  payload={json.dumps(payload)}")
        try:
            data = post(url, "/reset", payload, timeout)
            print(json.dumps(summarize_response(data), indent=2))
        except requests.RequestException as e:
            print(f"  error: {e}")
        return True
    if cmd in ("health", "hc"):
        try:
            data = get(url, "/health", timeout=10)
            print(json.dumps(data, indent=2))
        except requests.RequestException as e:
            print(f"  error: {e}")
        return True
    if cmd == "deep_health":
        try:
            data = get(url, "/deep_health", timeout=timeout)
            print(json.dumps(summarize_response(data), indent=2))
        except requests.RequestException as e:
            print(f"  error: {e}")
        return True

    print(f"  unknown command: {cmd!r} (type 'help')")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="localhost", help="server host (default: localhost)")
    parser.add_argument("--port", type=int, default=5000, help="server port (default: 5000)")
    parser.add_argument("--url", default=None, help="full base URL; overrides --host/--port")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        help=f"request timeout in seconds (default: {DEFAULT_TIMEOUT})")
    args = parser.parse_args()

    url = args.url.rstrip("/") if args.url else f"http://{args.host}:{args.port}"

    print(f"skyrl_server reset shell — target: {url}")
    print("type 'help' for commands, 'quit' to exit")

    while True:
        try:
            line = input(f"{url}> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not run_command(url, line, args.timeout):
            break


if __name__ == "__main__":
    main()
