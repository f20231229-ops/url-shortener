import sqlite3
import string
import random
import time
from datetime import datetime, timezone
from flask import Flask, request, redirect, render_template, jsonify, abort

app = Flask(__name__)
DB_PATH = "urls.db"


# ── DB setup ──────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS urls (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                short_id  TEXT    NOT NULL UNIQUE,
                long_url  TEXT    NOT NULL,
                created_at TEXT   NOT NULL,
                clicks    INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_short_id ON urls(short_id)")
        conn.commit()


# ── ID generation (collision-free) ────────────────────────────────────────────

CHARS = string.ascii_letters + string.digits   # 62-char alphabet
ID_LEN = 6                                     # 62^6 ≈ 56 billion combos


def generate_short_id() -> str:
    """Generate a unique 6-char alphanumeric ID, retrying on collision."""
    with get_db() as conn:
        for _ in range(10):                    # at most 10 attempts
            candidate = "".join(random.choices(CHARS, k=ID_LEN))
            exists = conn.execute(
                "SELECT 1 FROM urls WHERE short_id = ?", (candidate,)
            ).fetchone()
            if not exists:
                return candidate
    raise RuntimeError("Could not generate unique short ID after 10 attempts")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/shorten", methods=["POST"])
def shorten():
    data = request.get_json(silent=True) or {}
    long_url = (data.get("url") or "").strip()

    if not long_url:
        return jsonify({"error": "URL is required"}), 400
    if not long_url.startswith(("http://", "https://")):
        long_url = "https://" + long_url

    short_id = generate_short_id()
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    with get_db() as conn:
        conn.execute(
            "INSERT INTO urls (short_id, long_url, created_at) VALUES (?, ?, ?)",
            (short_id, long_url, created_at),
        )
        conn.commit()

    short_url = request.host_url + short_id
    return jsonify({"short_url": short_url, "short_id": short_id})


@app.route("/<short_id>")
def redirect_url(short_id):
    t0 = time.monotonic()
    with get_db() as conn:
        row = conn.execute(
            "SELECT long_url FROM urls WHERE short_id = ?", (short_id,)
        ).fetchone()
        if not row:
            abort(404)
        conn.execute(
            "UPDATE urls SET clicks = clicks + 1 WHERE short_id = ?", (short_id,)
        )
        conn.commit()

    elapsed_ms = (time.monotonic() - t0) * 1000
    # sub-100 ms redirect
    response = redirect(row["long_url"], code=302)
    response.headers["X-Redirect-Ms"] = f"{elapsed_ms:.2f}"
    return response


@app.route("/stats/<short_id>")
def stats(short_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM urls WHERE short_id = ?", (short_id,)
        ).fetchone()
    if not row:
        return jsonify({"error": "Not found"}), 404
    return jsonify({
        "short_id":   row["short_id"],
        "long_url":   row["long_url"],
        "clicks":     row["clicks"],
        "created_at": row["created_at"],
        "short_url":  request.host_url + row["short_id"],
    })


@app.route("/api/recent")
def recent():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT short_id, long_url, clicks, created_at "
            "FROM urls ORDER BY id DESC LIMIT 10"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.errorhandler(404)
def not_found(_):
    return render_template("404.html"), 404


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
