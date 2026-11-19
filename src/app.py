from flask import Flask, render_template, request, abort
import sqlite3
from pathlib import Path

app = Flask(__name__)
DB_PATH = Path("/app/data/cityguide.db") if Path("/app/data").exists() else Path(__file__).with_name("cityguide.db")
RATING_CHOICES = {str(value) for value in range(1, 6)}


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

        INSERT OR IGNORE INTO places
            (id, name, category, description, city, rating, active)
        VALUES
            (1, 'Old Town Square', 'Historic', 'A lively historic square with cafés and beautiful architecture.', 'Kyiv', 4.8, 1),
            (2, 'Riverside Park', 'Nature', 'A quiet green area for walking, cycling, and relaxing.', 'Kyiv', 4.5, 1),
            (3, 'Science Museum', 'Museum', 'Interactive exhibitions covering science and technology.', 'Kyiv', 4.7, 1),
            (4, 'Central Market', 'Food', 'A traditional market with local food and small vendors.', 'Kyiv', 4.2, 1),
            (5, 'Hidden Gallery', 'Art', 'A small contemporary art gallery with rotating exhibitions.', 'Kyiv', 4.6, 0);

        CREATE TABLE IF NOT EXISTS place_ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            place_id INTEGER NOT NULL,
            rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (place_id) REFERENCES places(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_place_ratings_place_id
            ON place_ratings(place_id);
        '''
    )
    conn.commit()
    conn.close()


def active_places_with_rating_aggregates(conn, query=""):
    params = []
    filters = ["p.active = 1"]

    if query:
        filters.append("p.name LIKE ?")
        params.append(f"%{query}%")

    return conn.execute(
        f"""
        SELECT
            p.*,
            AVG(pr.rating) AS average_rating,
            COUNT(pr.id) AS rating_count
        FROM places p
        LEFT JOIN place_ratings pr ON pr.place_id = p.id
        WHERE {' AND '.join(filters)}
        GROUP BY p.id
        ORDER BY average_rating DESC, p.name ASC
        """,
        params,
    ).fetchall()


def active_place_with_rating_aggregates(conn, place_id):
    return conn.execute(
        """
        SELECT
            p.*,
            AVG(pr.rating) AS average_rating,
            COUNT(pr.id) AS rating_count
        FROM places p
        LEFT JOIN place_ratings pr ON pr.place_id = p.id
        WHERE p.id = ? AND p.active = 1
        GROUP BY p.id
        """,
        (place_id,),
    ).fetchone()


def active_places_submitted_average(conn):
    return conn.execute(
        """
        SELECT AVG(pr.rating)
        FROM place_ratings pr
        JOIN places p ON p.id = pr.place_id
        WHERE p.active = 1
        """
    ).fetchone()[0]


def validate_rating_submission(rating_values):
    if not rating_values:
        return None, "Please select a rating from 1 to 5 stars."

    if len(rating_values) != 1:
        return None, "Please select exactly one rating from 1 to 5 stars."

    rating_value = rating_values[0].strip()
    if rating_value not in RATING_CHOICES:
        return None, "Please select a valid rating from 1 to 5 stars."

    return int(rating_value), None


def render_place_details(
    conn,
    place_id,
    *,
    success_message=None,
    validation_message=None,
    selected_rating=None,
):
    place = active_place_with_rating_aggregates(conn, place_id)
    if place is None:
        abort(404)

    return render_template(
        "place.html",
        place=place,
        success_message=success_message,
        validation_message=validation_message,
        selected_rating=selected_rating,
    )


@app.route("/")
def index():
    query = request.args.get("q", "").strip()

    conn = get_db()
    places = active_places_with_rating_aggregates(conn, query)
    total_places = conn.execute(
        "SELECT COUNT(*) FROM places WHERE active = 1"
    ).fetchone()[0]
    average_rating = active_places_submitted_average(conn)
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
    try:
        return render_place_details(conn, place_id)
    finally:
        conn.close()


@app.route("/place/<int:place_id>/rating", methods=["POST"])
def submit_rating(place_id):
    conn = get_db()
    try:
        place = active_place_with_rating_aggregates(conn, place_id)
        if place is None:
            abort(404)

        rating_values = request.form.getlist("rating")
        rating, validation_message = validate_rating_submission(rating_values)
        selected_rating = rating_values[0].strip() if len(rating_values) == 1 else None

        if validation_message:
            return (
                render_place_details(
                    conn,
                    place_id,
                    validation_message=validation_message,
                    selected_rating=selected_rating,
                ),
                400,
            )

        conn.execute(
            "INSERT INTO place_ratings (place_id, rating) VALUES (?, ?)",
            (place_id, rating),
        )
        conn.commit()

        return render_place_details(
            conn,
            place_id,
            success_message="Thank you! Your rating has been recorded.",
            selected_rating=str(rating),
        )
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
