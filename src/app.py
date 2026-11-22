from flask import Flask, render_template, request, abort, redirect, url_for
import sqlite3
from pathlib import Path

app = Flask(__name__)
DB_PATH = Path("/app/data/cityguide.db") if Path("/app/data").exists() else Path(__file__).with_name("cityguide.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute(
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
        )
        '''
    )

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(places)").fetchall()}
    if "rating_count" not in columns:
        conn.execute("ALTER TABLE places ADD COLUMN rating_count INTEGER NOT NULL DEFAULT 1")

    conn.executemany(
        '''
        INSERT OR IGNORE INTO places
            (id, name, category, description, city, rating, rating_count, active)
        VALUES
            (?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        [
            (1, 'Old Town Square', 'Historic', 'A lively historic square with cafés and beautiful architecture.', 'Kyiv', 4.8, 1, 1),
            (2, 'Riverside Park', 'Nature', 'A quiet green area for walking, cycling, and relaxing.', 'Kyiv', 4.5, 1, 1),
            (3, 'Science Museum', 'Museum', 'Interactive exhibitions covering science and technology.', 'Kyiv', 4.7, 1, 1),
            (4, 'Central Market', 'Food', 'A traditional market with local food and small vendors.', 'Kyiv', 4.2, 1, 1),
            (5, 'Hidden Gallery', 'Art', 'A small contemporary art gallery with rotating exhibitions.', 'Kyiv', 4.6, 1, 0),
        ],
    )

    conn.execute(
        '''
        UPDATE places
        SET rating_count = 1
        WHERE rating_count IS NULL
           OR typeof(rating_count) NOT IN ('integer', 'real')
           OR rating_count < 1
           OR CAST(rating_count AS INTEGER) != rating_count
        '''
    )

    conn.commit()
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

    total_places = conn.execute("SELECT COUNT(*) FROM places WHERE active = 1").fetchone()[0]
    average_rating = conn.execute("SELECT AVG(rating) FROM places WHERE active = 1").fetchone()[0]

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
    submitted = request.form.get("rating", "").strip()

    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        place = conn.execute(
            "SELECT rating, rating_count FROM places WHERE id = ? AND active = 1",
            (place_id,),
        ).fetchone()

        if place is None:
            conn.rollback()
            abort(404)

        if submitted not in {"1", "2", "3", "4", "5"}:
            conn.rollback()
            abort(400)

        submitted_rating = int(submitted)
        current_average = float(place["rating"])
        rating_count = int(place["rating_count"])
        if rating_count < 1:
            rating_count = 1

        new_count = rating_count + 1
        new_average = ((current_average * rating_count) + submitted_rating) / new_count

        conn.execute(
            "UPDATE places SET rating = ?, rating_count = ? WHERE id = ? AND active = 1",
            (new_average, new_count, place_id),
        )
        conn.commit()
    finally:
        conn.close()

    return redirect(url_for("place_details", place_id=place_id))


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
