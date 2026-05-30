import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path("leads.db")

# The pipeline stages a user can move a lead through.
# Order matters — used for the filter dropdown.
STATUS_OPTIONS = [
    "backlog",
    "contacted",
    "negotiating",
    "won",
    "lost",
    "stale",
]

# Only these fields can be edited from the My Leads view.
EDITABLE_FIELDS = {"status", "notes"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    place_id        TEXT    UNIQUE NOT NULL,
    business_name   TEXT,
    address         TEXT,
    phone           TEXT,
    website         TEXT,
    rating          REAL,
    review_count    INTEGER,
    categories      TEXT,
    score           INTEGER,
    reasoning       TEXT,
    flags           TEXT,
    emails_generic  TEXT,
    emails_personal TEXT,
    search_query    TEXT,
    status          TEXT NOT NULL DEFAULT 'backlog',
    notes           TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
)
"""


# Maps internal snake_case columns to the Title Case names used elsewhere
# in the app (so the My Leads table looks the same as a fresh search).
DB_TO_DISPLAY = {
    "id":              "ID",
    "place_id":        "place_id",
    "business_name":   "Business Name",
    "address":         "Address",
    "phone":           "Phone",
    "website":         "Website",
    "rating":          "Rating",
    "review_count":    "Number of Reviews",
    "categories":      "Categories",
    "score":           "Score",
    "reasoning":       "Reasoning",
    "flags":           "Flags",
    "emails_generic":  "Emails (Generic)",
    "emails_personal": "Emails (Personal)",
    "search_query":    "Search Query",
    "status":          "Status",
    "notes":           "Notes",
    "created_at":      "Created",
    "updated_at":      "Updated",
}


@contextmanager
def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with _connect() as conn:
        conn.execute(SCHEMA)


def _to_float(v):
    return float(v) if isinstance(v, (int, float)) else None


def _to_int(v):
    return int(v) if isinstance(v, (int, float)) else None


def save_leads(rows, query):
    """Upsert leads from a search batch.

    Returns (new_count, updated_count, new_place_ids). On conflict (existing
    place_id), scraped fields and AI scores are refreshed, but status, notes,
    and created_at are preserved.
    """
    new_count = 0
    updated_count = 0
    new_place_ids = []
    with _connect() as conn:
        for row in rows:
            place_id = row.get("place_id")
            if not place_id:
                continue

            already_exists = conn.execute(
                "SELECT 1 FROM leads WHERE place_id = ?", (place_id,)
            ).fetchone() is not None

            conn.execute(
                """
                INSERT INTO leads (
                    place_id, business_name, address, phone, website,
                    rating, review_count, categories, score, reasoning,
                    flags, emails_generic, emails_personal, search_query
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(place_id) DO UPDATE SET
                    business_name   = excluded.business_name,
                    address         = excluded.address,
                    phone           = excluded.phone,
                    website         = excluded.website,
                    rating          = excluded.rating,
                    review_count    = excluded.review_count,
                    categories      = excluded.categories,
                    score           = excluded.score,
                    reasoning       = excluded.reasoning,
                    flags           = excluded.flags,
                    emails_generic  = excluded.emails_generic,
                    emails_personal = excluded.emails_personal,
                    updated_at      = datetime('now')
                """,
                (
                    place_id,
                    row.get("Business Name"),
                    row.get("Address"),
                    row.get("Phone"),
                    row.get("Website"),
                    _to_float(row.get("Rating")),
                    _to_int(row.get("Number of Reviews")),
                    row.get("Categories"),
                    _to_int(row.get("Score")),
                    row.get("Reasoning"),
                    row.get("Flags"),
                    row.get("Emails (Generic)"),
                    row.get("Emails (Personal)"),
                    query,
                ),
            )
            if already_exists:
                updated_count += 1
            else:
                new_count += 1
                new_place_ids.append(place_id)
    return new_count, updated_count, new_place_ids


def update_lead(lead_id, **fields):
    """Update editable fields of a single lead. Auto-touches updated_at."""
    fields = {k: v for k, v in fields.items() if k in EDITABLE_FIELDS}
    if not fields:
        return
    set_clauses = [f"{col} = ?" for col in fields]
    set_clauses.append("updated_at = datetime('now')")
    sql = f"UPDATE leads SET {', '.join(set_clauses)} WHERE id = ?"
    values = list(fields.values()) + [lead_id]
    with _connect() as conn:
        conn.execute(sql, values)


def get_all_leads_for_display():
    """Return all leads as dicts with display-friendly column names,
    newest activity first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM leads ORDER BY updated_at DESC, id DESC"
        ).fetchall()
    return [
        {DB_TO_DISPLAY.get(k, k): v for k, v in dict(row).items()}
        for row in rows
    ]
