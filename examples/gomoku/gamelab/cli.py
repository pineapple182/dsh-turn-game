"""Command line interface: serve the game or drive it with one-liners."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import webbrowser
from typing import Any

from .presentation import SIDE_LABELS as SIDE_NAMES, render_board as _render_board, status_line
from .server import create_server

DEFAULT_URL = "http://127.0.0.1:8765"


def _base_url(value: str | None) -> str:
    return (value or os.environ.get("GAMELAB_URL") or DEFAULT_URL).rstrip("/")


def _request(
    base: str,
    path: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: float = 5.0,
) -> tuple[int, dict[str, Any]]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8") or "{}"
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"ok": False, "error": {"code": "http_error", "message": raw}}
    except urllib.error.URLError as exc:
        print(
            f"连不上 game-lab 服务（{base}）：{exc.reason}\n先运行：python -m gamelab serve",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


def render_board(state: dict[str, Any]) -> str:
    return f"{_render_board(state)}\n{status_line(state)}"


def _print_result(status: int, payload: dict[str, Any], as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif payload.get("ok"):
        print(_describe(payload))
        print()
        print(render_board(payload["state"]))
    else:
        error = payload.get("error", {})
        print(f"错误：{error.get('message', '未知错误')}（{error.get('code', '?')}）", file=sys.stderr)
    return 0 if payload.get("ok") else 1


def _describe(payload: dict[str, Any]) -> str:
    action = payload.get("action")
    if action == "place":
        move = payload["move"]
        return f"{SIDE_NAMES[move['player']]} 在 {move['notation']} 落子（第 {move['seq']} 手）"
    if action == "undo":
        move = payload["undo"]
        return f"已悔棋：{SIDE_NAMES[move['player']]} 的 {move['notation']} 被撤回"
    if action == "reset":
        return "已重开一局"
    return "操作完成"


def _cmd_serve(args: argparse.Namespace) -> int:
    server = create_server(args.host, args.port, quiet=args.quiet)
    url = server.url
    print(f"game-lab 已启动：{url}")
    print(f"  网页：{url}/")
    print(f"  JSON：{url}/api/state")
    print(f"  SSE ：{url}/api/stream")
    print("按 Ctrl+C 停止")
    if args.open:
        try:
            webbrowser.open(url)
        except Exception:  # pragma: no cover - browser launching is best effort
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        server.server_close()
    return 0


def _cmd_state(args: argparse.Namespace) -> int:
    base = _base_url(args.url)
    _, payload = _request(base, "/api/state")
    if args.board:
        print(render_board(payload))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _cmd_board(args: argparse.Namespace) -> int:
    base = _base_url(args.url)
    _, payload = _request(base, "/api/state")
    print(render_board(payload))
    return 0


def _cmd_command(args: argparse.Namespace, command: str, as_json: bool) -> int:
    base = _base_url(args.url)
    status, payload = _request(base, "/api/command", "POST", {"command": command})
    return _print_result(status, payload, as_json)


def _cmd_move(args: argparse.Namespace) -> int:
    base = _base_url(args.url)
    payload: dict[str, Any] = {"notation": args.coordinate}
    if args.actor:
        payload["as"] = args.actor
    status, payload = _request(base, "/api/move", "POST", payload)
    return _print_result(status, payload, args.json)


def _cmd_undo(args: argparse.Namespace) -> int:
    return _cmd_command(args, "undo", args.json)


def _cmd_reset(args: argparse.Namespace) -> int:
    return _cmd_command(args, "reset", args.json)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gamelab",
        description="game-lab：五子棋（浏览器 UI + JSON API + 命令行）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="启动本地服务（网页 + API）")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--quiet", action="store_true", help="不打印每条请求日志")
    serve.add_argument("--open", action="store_true", help="启动后尝试打开浏览器")
    serve.set_defaults(func=_cmd_serve)

    state = sub.add_parser("state", help="打印当前状态 JSON")
    state.add_argument("--url", default=None)
    state.add_argument("--board", action="store_true", help="改用棋盘图显示")
    state.set_defaults(func=_cmd_state)

    board = sub.add_parser("board", help="打印棋盘图")
    board.add_argument("--url", default=None)
    board.set_defaults(func=_cmd_board)

    move = sub.add_parser("move", help="落子，例如：gamelab move H8")
    move.add_argument("coordinate", help="坐标，如 H8 / A1 / O15")
    move.add_argument("--url", default=None)
    move.add_argument("--as", dest="actor", choices=("human", "agent"), default=None, help="人机对局中声明落子方")
    move.add_argument("--json", action="store_true", help="输出完整 JSON")
    move.set_defaults(func=_cmd_move)

    undo = sub.add_parser("undo", help="悔棋一步")
    undo.add_argument("--url", default=None)
    undo.add_argument("--json", action="store_true")
    undo.set_defaults(func=_cmd_undo)

    reset = sub.add_parser("reset", help="重开一局")
    reset.add_argument("--url", default=None)
    reset.add_argument("--json", action="store_true")
    reset.set_defaults(func=_cmd_reset)

    return parser


def main(argv: list[str] | None = None) -> int:
    # Windows consoles may default to a legacy code page; force UTF-8 so the
    # Chinese board labels never raise UnicodeEncodeError.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
