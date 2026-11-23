from flask import Flask, render_template, request, abort, redirect, url_for
import sqlite3
from pathlib import Path

app = Flask(__name__)
DB_PATH = Path("/app/data/cityguide.db") if Path("/app/data").exists() else Path(__file__).with_name("cityguide.db")
VALID_RATINGS = {"1", "2", "3", "4", "5"}


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _column_names(conn, table_name):
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})")}


def init_db():
    conn = get_db()
    try:
        conn.executescript(
            '''
            CREATE TABLE IF NOT EXISTS places (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                city TEXT NOT NULL,
                rating REAL NOT NULL,
                rating_count INTEGER NOT NULL DEFAULT 1,
                active INTEGER NOT NULL DEFAULT 1
            );
            '''
        )

        columns = _column_names(conn, "places")
        if "rating_count" not in columns:
            conn.execute(
                "ALTER TABLE places ADD COLUMN rating_count INTEGER NOT NULL DEFAULT 1"
            )

        # Existing rows represent one initial rating equal to their stored average.
        # Do not reset non-null counts so accepted visitor ratings persist across
        # subsequent init_db() calls using the same database.
        conn.execute(
            "UPDATE places SET rating_count = 1 "
            "WHERE rating_count IS NULL OR rating_count < 1"
        )

        conn.executescript(
            '''
            INSERT OR IGNORE INTO places
                (id, name, category, description, city, rating, rating_count, active)
            VALUES
                (1, 'Old Town Square', 'Historic', 'A lively historic square with cafés and beautiful architecture.', 'Kyiv', 4.8, 1, 1),
                (2, 'Riverside Park', 'Nature', 'A quiet green area for walking, cycling, and relaxing.', 'Kyiv', 4.5, 1, 1),
                (3, 'Science Museum', 'Museum', 'Interactive exhibitions covering science and technology.', 'Kyiv', 4.7, 1, 1),
                (4, 'Central Market', 'Food', 'A traditional market with local food and small vendors.', 'Kyiv', 4.2, 1, 1),
                (5, 'Hidden Gallery', 'Art', 'A small contemporary art gallery with rotating exhibitions.', 'Kyiv', 4.6, 1, 0);
            '''
        )
        conn.commit()
    finally:
        conn.close()


@app.route("/")
def index():
    query = request.args.get("q", "").strip()

    conn = get_db()

    if query:
        places = conn.execute(
            "SELECT * FROM places WHERE active = 1 AND name LIKE ? ORDER BY rating DESC",
            (f"%{query}%",),
        ).fetchall()
    else:
        places = conn.execute(
            "SELECT * FROM places WHERE active = 1 ORDER BY rating DESC"
        ).fetchall()

    total_places = conn.execute("SELECT COUNT(*) FROM places").fetchone()[0]
    average_rating = conn.execute(
        "SELECT AVG(rating) FROM places WHERE active = 1"
    ).fetchone()[0]

    conn.close()

    return render_template(
        "index.html",
        places=places,
        query=query,
        total_places=total_places,
        average_rating=round(average_rating or 0, 1),
    )


@app.route("/place/<int:place_id>")
def place_details(place_id):
    conn = get_db()
    place = conn.execute(
        "SELECT * FROM places WHERE id = ? AND active = 1",
        (place_id,),
    ).fetchone()
    conn.close()

    if place is None:
        abort(404)

    return render_template("place.html", place=place)


@app.route("/place/<int:place_id>/rate", methods=["POST"])
def rate_place(place_id):
    submitted_ratings = request.form.getlist("rating")
    if len(submitted_ratings) != 1:
        abort(400, description="Rating must be a whole number from 1 to 5.")

    rating_text = submitted_ratings[0].strip()
    if rating_text not in VALID_RATINGS:
        abort(400, description="Rating must be a whole number from 1 to 5.")

    rating_value = int(rating_text)

    conn = get_db()
    try:
        cursor = conn.execute(
            """
            UPDATE places
            SET rating = ((rating * rating_count) + ?) / (rating_count + 1),
                rating_count = rating_count + 1
            WHERE id = ? AND active = 1
            """,
            (rating_value, place_id),
        )

        if cursor.rowcount != 1:
            conn.rollback()
            abort(404)

        conn.commit()
    finally:
        conn.close()

    return redirect(url_for("place_details", place_id=place_id))


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
