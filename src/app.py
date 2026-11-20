from flask import Flask, render_template, request, abort, redirect, url_for
import sqlite3
from pathlib import Path

app = Flask(__name__)
DB_PATH = Path("/app/data/cityguide.db") if Path("/app/data").exists() else Path(__file__).with_name("cityguide.db")
VALID_RATING_VALUES = {"1", "2", "3", "4", "5"}


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def validate_rating_value(value):
    """Return an integer rating for accepted submitted values, otherwise None."""
    if value in VALID_RATING_VALUES:
        return int(value)
    return None


def get_active_place_with_rating(conn, place_id):
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
            rating INTEGER NOT NULL CHECK (rating IN (1, 2, 3, 4, 5)),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (place_id) REFERENCES places(id)
        );

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


@app.route("/")
def index():
    query = request.args.get("q", "").strip()

    conn = get_db()

    if query:
        places = conn.execute(
            """
            SELECT
                p.*,
                AVG(pr.rating) AS average_rating,
                COUNT(pr.id) AS rating_count
            FROM places AS p
            LEFT JOIN place_ratings AS pr ON pr.place_id = p.id
            WHERE p.active = 1 AND p.name LIKE ?
            GROUP BY p.id
            ORDER BY p.rating DESC
            """,
            (f"%{query}%",),
        ).fetchall()
    else:
        places = conn.execute(
            """
            SELECT
                p.*,
                AVG(pr.rating) AS average_rating,
                COUNT(pr.id) AS rating_count
            FROM places AS p
            LEFT JOIN place_ratings AS pr ON pr.place_id = p.id
            WHERE p.active = 1
            GROUP BY p.id
            ORDER BY p.rating DESC
            """
        ).fetchall()

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


@app.route("/place/<int:place_id>")
def place_details(place_id):
    conn = get_db()
    place = get_active_place_with_rating(conn, place_id)
    conn.close()

    if place is None:
        abort(404)

    return render_template("place.html", place=place)


@app.route("/place/<int:place_id>/ratings", methods=["POST"])
def submit_place_rating(place_id):
    conn = get_db()
    place = get_active_place_with_rating(conn, place_id)

    if place is None:
        conn.close()
        abort(404)

    rating = validate_rating_value(request.form.get("rating"))
    if rating is None:
        conn.close()
        return (
            render_template(
                "place.html",
                place=place,
                rating_error="Please choose a whole-star rating from 1 to 5.",
            ),
            400,
        )

    conn.execute(
        "INSERT INTO place_ratings (place_id, rating) VALUES (?, ?)",
        (place_id, rating),
    )
    conn.commit()
    conn.close()

    return redirect(url_for("place_details", place_id=place_id))


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
