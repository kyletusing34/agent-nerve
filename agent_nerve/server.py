from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .redaction import redact_json_like, redact_text
from .store import EVENT_KINDS, TASK_STATUSES, VISIBILITY, ClaimResult, Store


def json_bytes(body: dict | list) -> bytes:
    return json.dumps(body, separators=(",", ":")).encode("utf-8")


def env_store() -> Store:
    db_path = Path(os.environ.get("AGENT_NERVE_DB", "./data/agent_nerve.sqlite3"))
    return Store(db_path)


class AgentNerveHandler(BaseHTTPRequestHandler):
    store: Store
    api_key: str

    def log_message(self, fmt: str, *args) -> None:
        return

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/health":
            self.send_json({"ok": True})
            return
        if parsed.path == "/api/state":
            namespace = self.required_namespace(parsed.query)
            if namespace is None:
                return
            self.send_json(
                {
                    "namespace": namespace,
                    "tasks": self.store.list_tasks(namespace),
                    "events": self.store.list_events(namespace, 100),
                    "claims": self.store.list_claims(namespace),
                }
            )
            return
        if parsed.path == "/api/tasks":
            namespace = self.required_namespace(parsed.query)
            if namespace is None:
                return
            self.send_json(self.store.list_tasks(namespace))
            return
        if parsed.path == "/api/events":
            params = parse_qs(parsed.query)
            namespace = (params.get("namespace") or [""])[0].strip()
            if not namespace:
                self.send_error_json(HTTPStatus.BAD_REQUEST, "namespace is required")
                return
            try:
                limit = min(max(int((params.get("limit") or ["100"])[0]), 1), 500)
            except ValueError:
                self.send_error_json(HTTPStatus.BAD_REQUEST, "limit must be an integer")
                return
            self.send_json(self.store.list_events(namespace, limit))
            return
        if parsed.path == "/api/claims":
            namespace = self.required_namespace(parsed.query)
            if namespace is None:
                return
            self.send_json(self.store.list_claims(namespace))
            return
        self.send_error_json(HTTPStatus.NOT_FOUND, "unknown endpoint")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not self.authorized():
            self.send_error_json(HTTPStatus.UNAUTHORIZED, "missing or invalid API key")
            return
        if parsed.path == "/api/tasks":
            self.create_task()
            return
        if parsed.path == "/api/events":
            self.create_event()
            return
        if parsed.path == "/api/claims":
            self.create_claim()
            return
        self.send_error_json(HTTPStatus.NOT_FOUND, "unknown endpoint")

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        if not self.authorized():
            self.send_error_json(HTTPStatus.UNAUTHORIZED, "missing or invalid API key")
            return
        if parsed.path.startswith("/api/tasks/"):
            self.update_task(parsed.path)
            return
        self.send_error_json(HTTPStatus.NOT_FOUND, "unknown endpoint")

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        if not self.authorized():
            self.send_error_json(HTTPStatus.UNAUTHORIZED, "missing or invalid API key")
            return
        if parsed.path.startswith("/api/claims/"):
            self.delete_claim(parsed.path)
            return
        self.send_error_json(HTTPStatus.NOT_FOUND, "unknown endpoint")

    def required_namespace(self, query: str) -> str | None:
        params = parse_qs(query)
        namespace = (params.get("namespace") or [""])[0].strip()
        if not namespace:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "namespace is required")
            return None
        return namespace

    def authorized(self) -> bool:
        if not self.api_key:
            return True
        auth = self.headers.get("Authorization", "")
        token = self.headers.get("X-Agent-Nerve-Key", "")
        return auth == f"Bearer {self.api_key}" or token == self.api_key

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def send_json(self, body: dict | list, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json_bytes(body)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_error_json(self, status: HTTPStatus, message: str) -> None:
        self.send_json({"error": message}, status)

    def create_task(self) -> None:
        body = redact_json_like(self.read_json())
        namespace = str(body.get("namespace", "")).strip()
        title = str(body.get("title", "")).strip()
        status = str(body.get("status", "open")).strip()
        owner = str(body.get("owner", "")).strip()
        summary = str(body.get("summary", "")).strip()
        next_action = str(body.get("next_action", "")).strip()
        if not namespace or not title:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "namespace and title are required")
            return
        if status not in TASK_STATUSES:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "invalid task status")
            return
        row = self.store.create_task(namespace, title, status, owner, summary, next_action)
        self.send_json(row, HTTPStatus.CREATED)

    def update_task(self, path: str) -> None:
        try:
            task_id = int(path.rstrip("/").split("/")[-1])
        except ValueError:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "invalid task id")
            return
        body = redact_json_like(self.read_json())
        status = body.get("status")
        if status is not None and str(status) not in TASK_STATUSES:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "invalid task status")
            return
        row = self.store.update_task(
            task_id,
            status=str(status) if status is not None else None,
            owner=str(body["owner"]).strip() if "owner" in body else None,
            summary=str(body["summary"]).strip() if "summary" in body else None,
            next_action=str(body["next_action"]).strip() if "next_action" in body else None,
        )
        if row is None:
            self.send_error_json(HTTPStatus.NOT_FOUND, "task not found")
            return
        self.send_json(row)

    def create_event(self) -> None:
        body = redact_json_like(self.read_json())
        namespace = str(body.get("namespace", "")).strip()
        agent = str(body.get("agent", "")).strip()
        kind = str(body.get("kind", "")).strip()
        summary = str(body.get("summary", "")).strip()
        details = str(body.get("details", "")).strip()
        visibility = str(body.get("visibility", "shared")).strip()
        machine = str(body.get("machine", "")).strip()
        task_id = body.get("task_id")
        metadata = body.get("metadata") or {}
        if not namespace or not agent or not kind or not summary:
            self.send_error_json(
                HTTPStatus.BAD_REQUEST,
                "namespace, agent, kind, and summary are required",
            )
            return
        if kind not in EVENT_KINDS:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "invalid event kind")
            return
        if visibility not in VISIBILITY:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "invalid visibility")
            return
        if task_id in ("", None):
            task_id = None
        elif not isinstance(task_id, int):
            self.send_error_json(HTTPStatus.BAD_REQUEST, "task_id must be an integer")
            return
        row = self.store.create_event(
            namespace=namespace,
            task_id=task_id,
            agent=agent,
            machine=machine,
            kind=kind,
            summary=summary,
            details=details,
            visibility=visibility,
            metadata=metadata,
        )
        self.send_json(row, HTTPStatus.CREATED)

    def create_claim(self) -> None:
        body = redact_json_like(self.read_json())
        namespace = str(body.get("namespace", "")).strip()
        resource = str(body.get("resource", "")).strip()
        agent = str(body.get("agent", "")).strip()
        machine = str(body.get("machine", "")).strip()
        note = str(body.get("note", "")).strip()
        try:
            ttl_seconds = int(body.get("ttl_seconds", 1800))
        except ValueError:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "ttl_seconds must be an integer")
            return
        if not namespace or not resource or not agent:
            self.send_error_json(
                HTTPStatus.BAD_REQUEST,
                "namespace, resource, and agent are required",
            )
            return
        result = self.store.acquire_claim(
            namespace=namespace,
            resource=resource,
            agent=agent,
            machine=machine,
            note=note,
            ttl_seconds=ttl_seconds,
        )
        if result.ok:
            self.store.create_event(
                namespace=namespace,
                task_id=None,
                agent=agent,
                machine=machine,
                kind="claim_acquired",
                summary=f"Claimed {resource}",
                details=note,
                visibility="shared",
                metadata={"claim_id": result.row["id"], "resource": resource, "reason": result.reason},
            )
            self.send_json({"ok": True, "reason": result.reason, "claim": result.row}, HTTPStatus.CREATED)
            return
        self.send_json({"ok": False, "reason": result.reason, "claim": result.row}, HTTPStatus.CONFLICT)

    def delete_claim(self, path: str) -> None:
        try:
            claim_id = int(path.rstrip("/").split("/")[-1])
        except ValueError:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "invalid claim id")
            return
        row = self.store.release_claim(claim_id)
        if row is None:
            self.send_error_json(HTTPStatus.NOT_FOUND, "claim not found")
            return
        self.store.create_event(
            namespace=row["namespace"],
            task_id=None,
            agent=row["agent"],
            machine=row["machine"],
            kind="claim_released",
            summary=f"Released {row['resource']}",
            details=row["note"],
            visibility="shared",
            metadata={"claim_id": claim_id, "resource": row["resource"]},
        )
        self.send_json({"ok": True, "claim": row})


def make_handler(store: Store, api_key: str):
    class BoundHandler(AgentNerveHandler):
        pass

    BoundHandler.store = store
    BoundHandler.api_key = api_key
    return BoundHandler


def serve(host: str, port: int, db_path: Path, api_key: str) -> None:
    store = Store(db_path)
    handler = make_handler(store, api_key)
    server = ThreadingHTTPServer((host, port), handler)
    print(redact_text(f"Agent Nerve listening on http://{host}:{port}"))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
