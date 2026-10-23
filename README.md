# halcyon

An independent engineering practice's site — with a booking engine that is real, not a contact form with a calendar illustration.

The site is a single static page; the booking system behind it is a small Python service with a SQLite database, scheduling rules and a stateful API.

**KK (Conan Sultan Khan)** · [github.com/kkcyber2](https://github.com/kkcyber2) · kkdev9715@gmail.com

## Run it

```bash
python -m app.server --port 8000
# open http://127.0.0.1:8000
```

No dependencies — the server, the scheduling engine and the data layer are all standard library.

## What is actually implemented

**Scheduling rules** (`app/booking.py`) — the part most booking widgets fake:

| Rule | Behaviour |
| --- | --- |
| Business hours | 09:00–18:00, Mon–Fri; weekends refused |
| Lunch | 12:30–13:30 is never bookable |
| Notice | 12 hours minimum; next Monday when booking over a weekend |
| Duration | 30 / 60 / 90 / 120 minutes by session kind |
| Prep buffer | 15 min after a discovery call, 30 min before a workshop |
| Overlap | half-open intervals, so touching edges are not a clash |
| Concurrency | a second request for the same slot gets `409`, enforced by a unique index in SQLite |

Every refusal returns a **machine-readable reason** (`outside_hours`, `no_buffer`, `overlap`, `too_short_notice`, `closed`, `past`) which the UI renders as a short label on the disabled slot, so a greyed-out time always explains itself.

**API**

```
GET  /api/booking/availability?kind=discovery&date=2026-11-02
GET  /api/booking/next?kind=review
POST /api/booking            {kind, start, name, email, brief}
GET  /api/booking/<ref>
```

**Front end** (`static/`) — hand-written CSS and JS, no framework. A fixed status bar, a data panel as the hero visual, and a booking grid that mirrors the server's rules.

## Tests

```bash
python -m pytest tests/ -q
```

39 tests: scheduling rules (including the refusal cases), persistence, and end-to-end API calls against a real HTTP server on an ephemeral port.

## Structure

```
app/booking.py   scheduling engine — pure functions, no I/O
app/store.py     SQLite persistence
app/server.py    HTTP API + static files
static/          index.html, styles.css, app.js
tests/           rule tests + live API tests
```

## Licence

MIT — see [LICENSE](LICENSE).
