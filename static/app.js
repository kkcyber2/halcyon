// Halcyon front end. Talks to the same booking rules the server enforces, so a
// slot shown as available is a slot the API will accept.

const $ = (sel) => document.querySelector(sel);

const kindEl = $("#kind");
const dayEl = $("#day");
const gridEl = $("#grid");
const formEl = $("#form");
const chosenEl = $("#chosen");
const errEl = $("#err");
const confirmedEl = $("#confirmed");

let selected = null;

/* --------------------------------------------------------------- clock */
function tick() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  const clock = $("#hud-clock");
  if (clock) clock.textContent = `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}`;
}
tick();
setInterval(tick, 1000);

/* ---------------------------------------------------------------- date */
function isoToday(offset = 3) {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return d.toISOString().slice(0, 10);
}
dayEl.value = isoToday();
dayEl.min = isoToday(0);

/* ---------------------------------------------------------- rendering */
const REASON_TEXT = {
  closed: "closed",
  outside_hours: "out of hours",
  too_short_notice: "too soon",
  overlap: "taken",
  no_buffer: "prep time",
  past: "passed",
};

function renderSlot(slot) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "slot";
  const time = new Date(slot.start).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  btn.innerHTML = `<span>${time}</span>`;
  if (slot.allowed) {
    btn.dataset.start = slot.start;
    btn.addEventListener("click", () => choose(slot));
  } else {
    btn.setAttribute("aria-disabled", "true");
    btn.disabled = true;
    const why = document.createElement("small");
    why.textContent = REASON_TEXT[slot.reason] || slot.reason;
    btn.appendChild(why);
  }
  return btn;
}

async function loadGrid() {
  gridEl.innerHTML = "<p class='note'>Loading the calendar…</p>";
  try {
    const res = await fetch(
      `/api/booking/availability?kind=${kindEl.value}&date=${dayEl.value}`
    );
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "could not load");

    gridEl.innerHTML = "";
    if (!data.slots.length) {
      gridEl.innerHTML = "<p class='note'>Closed that day. Pick a weekday.</p>";
      return;
    }
    for (const slot of data.slots) gridEl.appendChild(renderSlot(slot));
  } catch (e) {
    // textContent, not innerHTML: the message can carry text from the server,
    // and building markup from it would turn a stray '<' in an error into
    // executable HTML the moment an error starts including user input.
    const err = document.createElement("p");
    err.className = "err";
    err.textContent = e.message;
    gridEl.replaceChildren(err);
  }
}

function choose(slot) {
  selected = { ...slot, kind: kindEl.value };
  chosenEl.textContent = new Date(slot.start).toLocaleString([], {
    weekday: "long",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  formEl.hidden = false;
  confirmedEl.hidden = true;
  formEl.scrollIntoView({ behavior: "smooth", block: "center" });
}

/* ---------------------------------------------------------- submitting */
formEl.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  errEl.hidden = true;

  const fd = new FormData(formEl);
  const payload = {
    kind: selected.kind,
    start: selected.start,
    name: fd.get("name"),
    email: fd.get("email"),
    company: fd.get("company"),
    brief: fd.get("brief"),
  };

  try {
    const res = await fetch("/api/booking", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();

    if (!res.ok) {
      errEl.textContent = data.details
        ? data.details.join(" ")
        : data.detail || data.error || "Could not book that slot.";
      errEl.hidden = false;
      if (res.status === 409) loadGrid();
      return;
    }

    formEl.hidden = true;
    formEl.reset();
    confirmedEl.hidden = false;
    $("#ref").textContent = `Reference ${data.reference} · ${data.label} · ${new Date(
      data.start
    ).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit", hour12: false })}`;
    loadGrid();
  } catch (e) {
    errEl.textContent = "Network error — please try again.";
    errEl.hidden = false;
  }
});

/* ------------------------------------------------------------- wiring */
kindEl.addEventListener("change", loadGrid);
dayEl.addEventListener("change", loadGrid);

$("#find").addEventListener("click", async () => {
  const res = await fetch(`/api/booking/next?kind=${kindEl.value}`);
  const data = await res.json();
  if (!data.available) {
    gridEl.innerHTML = "<p class='note'>No openings in the next three weeks.</p>";
    return;
  }
  dayEl.value = data.start.slice(0, 10);
  await loadGrid();
});

loadGrid();
