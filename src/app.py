import os
import sqlite3
from pathlib import Path

from flask import Flask, abort, flash, redirect, render_template, request, url_for

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get(
    "CITYGUIDE_SECRET_KEY",
    app.config.get("SECRET_KEY") or "cityguide-demo-secret-key",
)
DB_PATH = Path("/app/data/cityguide.db") if Path("/app/data").exists() else Path(__file__).with_name("cityguide.db")


RATING_VALUES = {"1", "2", "3", "4", "5"}


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript(
        '''
        CREATE TABLE IF NOT EXISTS places (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT NOT NULL,
            city TEXT NOT NULL,
            rating REAL NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS place_ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            place_id INTEGER NOT NULL,
            rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (place_id) REFERENCES places(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_place_ratings_place_id
            ON place_ratings(place_id);

        INSERT OR IGNORE INTO places
            (id, name, category, description, city, rating, active)
        VALUES
            (1, 'Old Town Square', 'Historic', 'A lively historic square with cafés and beautiful architecture.', 'Kyiv', 4.8, 1),
            (2, 'Riverside Park', 'Nature', 'A quiet green area for walking, cycling, and relaxing.', 'Kyiv', 4.5, 1),
            (3, 'Science Museum', 'Museum', 'Interactive exhibitions covering science and technology.', 'Kyiv', 4.7, 1),
            (4, 'Central Market', 'Food', 'A traditional market with local food and small vendors.', 'Kyiv', 4.2, 1),
            (5, 'Hidden Gallery', 'Art', 'A small contemporary art gallery with rotating exhibitions.', 'Kyiv', 4.6, 0);
        '''
    )
    conn.commit()
    conn.close()


def _active_places_query(search_query=None):
    where_clause = "WHERE p.active = 1"
    params = ()

    if search_query:
        where_clause += " AND p.name LIKE ?"
        params = (f"%{search_query}%",)

    sql = f"""
        SELECT
            p.*,
            AVG(pr.rating) AS average_rating,
            COUNT(pr.id) AS rating_count
        FROM places AS p
        LEFT JOIN place_ratings AS pr ON pr.place_id = p.id
        {where_clause}
        GROUP BY p.id
        ORDER BY p.rating DESC
    """
    return sql, params


def get_active_places(conn, search_query=None):
    sql, params = _active_places_query(search_query)
    return conn.execute(sql, params).fetchall()


def get_active_place(conn, place_id):
    return conn.execute(
        """
        SELECT
            p.*,
            AVG(pr.rating) AS average_rating,
            COUNT(pr.id) AS rating_count
        FROM places AS p
        LEFT JOIN place_ratings AS pr ON pr.place_id = p.id
        WHERE p.id = ? AND p.active = 1
        GROUP BY p.id
        """,
        (place_id,),
    ).fetchone()


def parse_rating(raw_rating):
    if raw_rating is None:
        return None

    rating_text = raw_rating.strip()
    if rating_text not in RATING_VALUES:
        return None

    return int(rating_text)


@app.route("/")
def index():
    query = request.args.get("q", "").strip()

    conn = get_db()
    places = get_active_places(conn, query)
    total_places = conn.execute("SELECT COUNT(*) FROM places").fetchone()[0]
    average_rating = conn.execute("SELECT AVG(rating) FROM places").fetchone()[0]
    conn.close()

    return render_template(
        "index.html",
        places=places,
        query=query,
        total_places=total_places,
        average_rating=round(average_rating or 0, 1),
    )


@app.route("/place/<int:place_id>", methods=["GET", "POST"])
def place_details(place_id):
    conn = get_db()
    place = get_active_place(conn, place_id)

    if place is None:
        conn.close()
        abort(404)

    if request.method == "POST":
        rating = parse_rating(request.form.get("rating"))

        if rating is None:
            conn.close()
            flash("Please choose a whole-star rating from 1 to 5.", "error")
            return render_template("place.html", place=place), 400

        conn.execute(
            "INSERT INTO place_ratings (place_id, rating) VALUES (?, ?)",
            (place_id, rating),
        )
        conn.commit()
        conn.close()

        flash(f"Thank you! Your {rating}-star rating was submitted.", "success")
        return redirect(url_for("place_details", place_id=place_id))

    conn.close()
    return render_template("place.html", place=place)


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
