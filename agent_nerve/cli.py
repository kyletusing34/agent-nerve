from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from pathlib import Path
from urllib import error, request

from .redaction import redact_json_like
from .server import serve

DEFAULT_SERVER = os.environ.get("AGENT_NERVE_SERVER", "http://127.0.0.1:8787")
DEFAULT_QUEUE = Path(os.environ.get("AGENT_NERVE_QUEUE_FILE", "./data/queue.jsonl"))


def api_key_from_env() -> str:
    return os.environ.get("AGENT_NERVE_API_KEY", "").strip()


def post(path: str, body: dict, api_key: str) -> dict:
    payload = json.dumps(redact_json_like(body)).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "agent-nerve/0.1.0",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = request.Request(f"{DEFAULT_SERVER}{path}", data=payload, headers=headers, method="POST")
    with request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def patch(path: str, body: dict, api_key: str) -> dict:
    payload = json.dumps(redact_json_like(body)).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "agent-nerve/0.1.0",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = request.Request(f"{DEFAULT_SERVER}{path}", data=payload, headers=headers, method="PATCH")
    with request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def delete(path: str, api_key: str) -> dict:
    headers = {"User-Agent": "agent-nerve/0.1.0"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = request.Request(f"{DEFAULT_SERVER}{path}", headers=headers, method="DELETE")
    with request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def get(path: str) -> dict | list:
    req = request.Request(f"{DEFAULT_SERVER}{path}", headers={"User-Agent": "agent-nerve/0.1.0"})
    with request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def queue_event(entry: dict) -> None:
    DEFAULT_QUEUE.parent.mkdir(parents=True, exist_ok=True)
    with DEFAULT_QUEUE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, separators=(",", ":")) + "\n")


def flush_queue(api_key: str) -> None:
    if not DEFAULT_QUEUE.exists():
        return
    pending = [
        json.loads(line)
        for line in DEFAULT_QUEUE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    failed: list[dict] = []
    for entry in pending:
        try:
            post("/api/events", entry, api_key)
        except Exception:
            failed.append(entry)
    if failed:
        DEFAULT_QUEUE.write_text(
            "".join(json.dumps(item, separators=(",", ":")) + "\n" for item in failed),
            encoding="utf-8",
        )
    else:
        DEFAULT_QUEUE.unlink()


def print_json(value) -> None:
    print(json.dumps(value, indent=2))


def serve_cmd(args: argparse.Namespace) -> int:
    serve(args.host, args.port, Path(args.db), args.api_key or api_key_from_env())
    return 0


def task_create_cmd(args: argparse.Namespace) -> int:
    body = {
        "namespace": args.namespace,
        "title": args.title,
        "status": args.status,
        "owner": args.owner,
        "summary": args.summary,
        "next_action": args.next_action,
    }
    print_json(post("/api/tasks", body, args.api_key or api_key_from_env()))
    return 0


def task_update_cmd(args: argparse.Namespace) -> int:
    body = {}
    if args.status is not None:
        body["status"] = args.status
    if args.owner is not None:
        body["owner"] = args.owner
    if args.summary is not None:
        body["summary"] = args.summary
    if args.next_action is not None:
        body["next_action"] = args.next_action
    print_json(patch(f"/api/tasks/{args.task_id}", body, args.api_key or api_key_from_env()))
    return 0


def task_list_cmd(args: argparse.Namespace) -> int:
    print_json(get(f"/api/tasks?namespace={args.namespace}"))
    return 0


def event_emit_cmd(args: argparse.Namespace) -> int:
    body = {
        "namespace": args.namespace,
        "agent": args.agent,
        "machine": args.machine or socket.gethostname(),
        "kind": args.kind,
        "summary": args.summary,
        "details": args.details,
        "visibility": args.visibility,
        "metadata": json.loads(args.metadata) if args.metadata else {},
    }
    if args.task_id is not None:
        body["task_id"] = args.task_id
    api_key = args.api_key or api_key_from_env()
    try:
        print_json(post("/api/events", body, api_key))
        flush_queue(api_key)
    except Exception as exc:
        queue_event(body)
        print(f"Queued event because server was unreachable: {exc}", file=sys.stderr)
    return 0


def event_tail_cmd(args: argparse.Namespace) -> int:
    print_json(get(f"/api/events?namespace={args.namespace}&limit={args.limit}"))
    return 0


def claim_acquire_cmd(args: argparse.Namespace) -> int:
    body = {
        "namespace": args.namespace,
        "resource": args.resource,
        "agent": args.agent,
        "machine": args.machine or socket.gethostname(),
        "ttl_seconds": args.ttl_seconds,
        "note": args.note,
    }
    try:
        result = post("/api/claims", body, args.api_key or api_key_from_env())
        print_json(result)
        return 0
    except error.HTTPError as exc:
        payload = exc.read().decode("utf-8")
        print(payload, file=sys.stderr)
        return 1


def claim_release_cmd(args: argparse.Namespace) -> int:
    print_json(delete(f"/api/claims/{args.claim_id}", args.api_key or api_key_from_env()))
    return 0


def claim_list_cmd(args: argparse.Namespace) -> int:
    print_json(get(f"/api/claims?namespace={args.namespace}"))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-nerve")
    sub = parser.add_subparsers(dest="command", required=True)

    serve_parser = sub.add_parser("serve")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8787)
    serve_parser.add_argument("--db", default="./data/agent_nerve.sqlite3")
    serve_parser.add_argument("--api-key", default="")
    serve_parser.set_defaults(func=serve_cmd)

    task_parser = sub.add_parser("task")
    task_sub = task_parser.add_subparsers(dest="task_command", required=True)

    task_create = task_sub.add_parser("create")
    task_create.add_argument("--namespace", required=True)
    task_create.add_argument("--title", required=True)
    task_create.add_argument("--status", default="open")
    task_create.add_argument("--owner", default="")
    task_create.add_argument("--summary", default="")
    task_create.add_argument("--next-action", default="")
    task_create.add_argument("--api-key", default="")
    task_create.set_defaults(func=task_create_cmd)

    task_update = task_sub.add_parser("update")
    task_update.add_argument("--task-id", required=True, type=int)
    task_update.add_argument("--status")
    task_update.add_argument("--owner")
    task_update.add_argument("--summary")
    task_update.add_argument("--next-action")
    task_update.add_argument("--api-key", default="")
    task_update.set_defaults(func=task_update_cmd)

    task_list = task_sub.add_parser("list")
    task_list.add_argument("--namespace", required=True)
    task_list.set_defaults(func=task_list_cmd)

    event_parser = sub.add_parser("event")
    event_sub = event_parser.add_subparsers(dest="event_command", required=True)

    event_emit = event_sub.add_parser("emit")
    event_emit.add_argument("--namespace", required=True)
    event_emit.add_argument("--agent", required=True)
    event_emit.add_argument("--kind", required=True)
    event_emit.add_argument("--summary", required=True)
    event_emit.add_argument("--details", default="")
    event_emit.add_argument("--visibility", default="shared")
    event_emit.add_argument("--machine", default="")
    event_emit.add_argument("--task-id", type=int)
    event_emit.add_argument("--metadata", default="")
    event_emit.add_argument("--api-key", default="")
    event_emit.set_defaults(func=event_emit_cmd)

    event_tail = event_sub.add_parser("tail")
    event_tail.add_argument("--namespace", required=True)
    event_tail.add_argument("--limit", type=int, default=20)
    event_tail.set_defaults(func=event_tail_cmd)

    claim_parser = sub.add_parser("claim")
    claim_sub = claim_parser.add_subparsers(dest="claim_command", required=True)

    claim_acquire = claim_sub.add_parser("acquire")
    claim_acquire.add_argument("--namespace", required=True)
    claim_acquire.add_argument("--resource", required=True)
    claim_acquire.add_argument("--agent", required=True)
    claim_acquire.add_argument("--machine", default="")
    claim_acquire.add_argument("--ttl-seconds", type=int, default=1800)
    claim_acquire.add_argument("--note", default="")
    claim_acquire.add_argument("--api-key", default="")
    claim_acquire.set_defaults(func=claim_acquire_cmd)

    claim_release = claim_sub.add_parser("release")
    claim_release.add_argument("--claim-id", required=True, type=int)
    claim_release.add_argument("--api-key", default="")
    claim_release.set_defaults(func=claim_release_cmd)

    claim_list = claim_sub.add_parser("list")
    claim_list.add_argument("--namespace", required=True)
    claim_list.set_defaults(func=claim_list_cmd)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
