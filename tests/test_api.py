"""End-to-end API tests against a real HTTP server on an ephemeral port."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from http.server import HTTPServer
from pathlib import Path

import pytest

from app import store
from app.server import Handler


@pytest.fixture()
def server(tmp_path):
    db = str(tmp_path / "test.db")
    store.DB_PATH = db
    store.init()
    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()
    httpd.server_close()


def get(url, path):
    try:
        with urllib.request.urlopen(url + path) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def post(url, path, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url + path, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def a_weekday():
    """The next Monday at least 3 days out, so notice rules never interfere."""
    d = datetime.now().date() + timedelta(days=3)
    while d.weekday() != 0:
        d += timedelta(days=1)
    return d


class TestReadEndpoints:
    def test_health(self, server):
        status, body = get(server, "/api/health")
        assert status == 200 and body["ok"] is True

    def test_kinds_lists_all_four(self, server):
        status, body = get(server, "/api/booking/kinds")
        assert status == 200
        assert {k["id"] for k in body["kinds"]} == {"discovery", "workshop", "review", "retainer"}

    def test_availability_returns_a_grid(self, server):
        day = a_weekday()
        status, body = get(server, f"/api/booking/availability?kind=discovery&date={day}")
        assert status == 200
        assert body["date"] == day.isoformat()
        assert len(body["slots"]) >= 8
        assert all("allowed" in s and "reason" in s for s in body["slots"])

    def test_availability_rejects_bad_date(self, server):
        status, body = get(server, "/api/booking/availability?date=not-a-date")
        assert status == 400 and "date" in body["error"]

    def test_availability_rejects_bad_kind(self, server):
        status, body = get(server, f"/api/booking/availability?kind=nope&date={a_weekday()}")
        assert status == 400

    def test_next_offers_something(self, server):
        status, body = get(server, "/api/booking/next?kind=discovery")
        assert status == 200 and body["available"] is True
        assert datetime.fromisoformat(body["start"]) > datetime.now()

    def test_static_index_is_served(self, server):
        with urllib.request.urlopen(server + "/") as r:
            html = r.read().decode()
        assert r.status == 200 and "Halcyon" in html


class TestCreateBooking:
    def test_valid_booking_is_created(self, server):
        day = a_weekday()
        payload = {
            "kind": "discovery",
            "start": f"{day}T10:00:00",
            "name": "Ada Lovelace",
            "email": "ada@example.com",
            "brief": "We need an audit of our auth model.",
        }
        status, body = post(server, "/api/booking", payload)
        assert status == 201, body
        assert body["reference"].startswith("HC-")
        assert body["label"] == "Discovery call"

        _, listed = get(server, "/api/booking/list")
        assert len(listed["bookings"]) == 1
        assert listed["bookings"][0]["email"] == "ada@example.com"

    def test_double_booking_is_refused(self, server):
        day = a_weekday()
        payload = {
            "kind": "discovery", "start": f"{day}T10:00:00",
            "name": "Ada", "email": "ada@example.com", "brief": "x" * 30,
        }
        assert post(server, "/api/booking", payload)[0] == 201
        status, body = post(server, "/api/booking", payload)
        assert status == 409
        assert body["reason"] == "overlap"

    def test_bad_email_is_refused(self, server):
        day = a_weekday()
        payload = {"kind": "discovery", "start": f"{day}T11:00:00",
                   "name": "Ada", "email": "not-an-email", "brief": "x" * 30}
        status, body = post(server, "/api/booking", payload)
        assert status == 422 and any("email" in d.lower() for d in body["details"])

    def test_weekend_is_refused(self, server):
        day = a_weekday() + timedelta(days=5)  # Saturday
        payload = {"kind": "discovery", "start": f"{day}T10:00:00",
                   "name": "Ada", "email": "ada@example.com", "brief": "x" * 30}
        status, body = post(server, "/api/booking", payload)
        assert status == 409 and body["reason"] == "closed"

    def test_missing_body_is_refused(self, server):
        req = urllib.request.Request(server + "/api/booking", data=b"",
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req)
            assert False, "should have failed"
        except urllib.error.HTTPError as e:
            assert e.code == 400

    def test_unknown_payload_field_is_ignored_not_crashing(self, server):
        day = a_weekday()
        payload = {"kind": "review", "start": f"{day}T15:00:00", "name": "Ada",
                   "email": "ada@example.com", "brief": "x" * 30, "nonsense": {"a": 1}}
        status, body = post(server, "/api/booking", payload)
        assert status == 201, body


class TestEnquiry:
    def test_valid_enquiry(self, server):
        status, body = post(server, "/api/enquiry", {
            "name": "Grace", "email": "grace@example.com",
            "budget": "10-25k", "message": "We are rebuilding our payment pipeline and need help.",
        })
        assert status == 201 and body["ok"] is True

    def test_short_message_refused(self, server):
        status, body = post(server, "/api/enquiry", {
            "name": "Grace", "email": "grace@example.com", "message": "hi",
        })
        assert status == 422


class TestBookingLookup:
    """GET /api/booking/<ref> is documented in the README, so it must exist."""

    def test_created_booking_is_fetchable_by_reference(self, server):
        status, created = post(server, "/api/booking", {
            "kind": "review", "start": "2026-11-04T15:00",
            "name": "Lookup Person", "email": "lookup@example.com", "brief": "find me",
        })
        assert status == 201
        ref = created["reference"]

        status, body = get(server, f"/api/booking/{ref}")
        assert status == 200
        assert body["reference"] == ref
        assert body["name"] == "Lookup Person"
        assert body["brief"] == "find me"

    def test_unknown_reference_is_404_not_500(self, server):
        status, body = get(server, "/api/booking/HC-DOESNOT")
        assert status == 404
        assert "error" in body

    def test_list_route_still_wins_over_reference_route(self, server):
        """A reference-shaped path must not swallow /api/booking/list."""
        status, body = get(server, "/api/booking/list")
        assert status == 200
        assert "bookings" in body
