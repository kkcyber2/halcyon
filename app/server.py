"""HTTP API + static site, standard library only.

Deliberately dependency-free: the whole point of this repo is that a client can
run it with `python -m app.server` and nothing else. The booking rules live in
app/booking.py and the persistence in app/store.py, so this file is wiring.
"""
from __future__ import annotations

import json
import re
import secrets
import sys
from datetime import date, datetime, timedelta
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app import store
from app.booking import (
    KIND_LABEL,
    KIND_SPEC,
    Reason,
    SlotKind,
    day_availability,
    evaluate,
    next_available,
)

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


class Handler(SimpleHTTPRequestHandler):
    server_version = "Halcyon/1.0"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    # ---------------------------------------------------------------- helpers
    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if length <= 0 or length > 64_000:
            return None
        try:
            return json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # ------------------------------------------------------------------- GET
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/health":
            return self._send_json({"ok": True, "service": "halcyon"})

        if path == "/api/booking/kinds":
            return self._send_json({
                "kinds": [
                    {
                        "id": k.value,
                        "label": KIND_LABEL[k],
                        "duration_min": KIND_SPEC[k][0],
                        "buffer_min": KIND_SPEC[k][1],
                    }
                    for k in SlotKind
                ]
            })

        if path == "/api/booking/availability":
            q = parse_qs(parsed.query)
            kind_raw = q.get("kind", ["discovery"])[0]
            try:
                kind = SlotKind(kind_raw)
            except ValueError:
                return self._send_json({"error": "unknown kind"}, 400)
            try:
                on = date.fromisoformat(q.get("date", [""])[0])
            except ValueError:
                return self._send_json({"error": "date must be YYYY-MM-DD"}, 400)

            bookings = store.list_bookings()
            grid = day_availability(on, kind, bookings, datetime.now())
            return self._send_json({
                "date": on.isoformat(),
                "kind": kind.value,
                "slots": [
                    {
                        "start": d.start.isoformat(timespec="minutes"),
                        "allowed": d.allowed,
                        "reason": d.reason.value,
                        "detail": d.detail,
                    }
                    for d in grid
                ],
            })

        if path == "/api/booking/next":
            q = parse_qs(parsed.query)
            try:
                kind = SlotKind(q.get("kind", ["discovery"])[0])
            except ValueError:
                return self._send_json({"error": "unknown kind"}, 400)
            d = next_available(kind, datetime.now(), store.list_bookings())
            if d is None:
                return self._send_json({"available": False}), 200
            return self._send_json({
                "available": True,
                "start": d.start.isoformat(timespec="minutes"),
                "end": d.end.isoformat(timespec="minutes"),
            })

        if path == "/api/booking/list":
            return self._send_json({"bookings": store.list_bookings_detail()})

        if path.startswith("/api/booking/"):
            reference = path.rsplit("/", 1)[-1]
            detail = store.get_booking_detail(reference)
            if detail is None:
                return self._send_json({"error": "no booking with that reference"}, 404)
            return self._send_json(detail)

        if path == "/":
            self.path = "/index.html"

        return super().do_GET()

    # ------------------------------------------------------------------ POST
    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        payload = self._read_json()
        if payload is None:
            return self._send_json({"error": "expected a JSON body"}, 400)

        if parsed.path == "/api/booking":
            return self._create_booking(payload)

        if parsed.path == "/api/enquiry":
            return self._create_enquiry(payload)

        return self._send_json({"error": "not found"}, 404)

    def _create_booking(self, payload: dict) -> None:
        errors = []

        name = str(payload.get("name", "")).strip()
        email = str(payload.get("email", "")).strip()
        brief = str(payload.get("brief", "")).strip()
        company = str(payload.get("company", "")).strip()

        if len(name) < 2:
            errors.append("Please give your name.")
        if not EMAIL_RE.match(email):
            errors.append("That email address does not look valid.")
        if len(brief) > 4000:
            errors.append("Please keep the brief under 4000 characters.")

        try:
            kind = SlotKind(str(payload.get("kind", "discovery")))
        except ValueError:
            errors.append("Unknown session type.")
            kind = SlotKind.DISCOVERY

        try:
            start = datetime.fromisoformat(str(payload.get("start", "")))
        except ValueError:
            errors.append("Pick a start time.")
            start = None

        if errors:
            return self._send_json({"error": "validation failed", "details": errors}, 422)

        decision = evaluate(kind, start, store.list_bookings(), datetime.now())
        if not decision.allowed:
            return self._send_json(
                {
                    "error": "slot unavailable",
                    "reason": decision.reason.value,
                    "detail": decision.detail,
                },
                409,
            )

        reference = f"HC-{secrets.token_hex(3).upper()}"
        duration = KIND_SPEC[kind][0]
        store.add_booking(kind, start, duration, name, email, reference, company, brief)

        return self._send_json(
            {
                "ok": True,
                "reference": reference,
                "kind": kind.value,
                "label": KIND_LABEL[kind],
                "start": start.isoformat(timespec="minutes"),
                "end": (start + timedelta(minutes=duration)).isoformat(timespec="minutes"),
                "name": name,
            },
            201,
        )

    def _create_enquiry(self, payload: dict) -> None:
        name = str(payload.get("name", "")).strip()
        email = str(payload.get("email", "")).strip()
        message = str(payload.get("message", "")).strip()
        budget = str(payload.get("budget", "")).strip()

        errors = []
        if len(name) < 2:
            errors.append("Please give your name.")
        if not EMAIL_RE.match(email):
            errors.append("That email address does not look valid.")
        if len(message) < 20:
            errors.append("Tell me a little more about the problem (20+ characters).")

        if errors:
            return self._send_json({"error": "validation failed", "details": errors}, 422)

        store.add_enquiry(name, email, message, budget)
        return self._send_json({"ok": True}, 201)


def serve(host: str = "127.0.0.1", port: int = 8099, db: str | None = None) -> None:
    if db:
        store.DB_PATH = db
    store.init()
    httpd = HTTPServer((host, port), Handler)
    print(f"halcyon on http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8099)
    p.add_argument("--db", default=None)
    a = p.parse_args()
    serve(a.host, a.port, a.db)
