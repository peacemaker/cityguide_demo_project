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

        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            place_id INTEGER NOT NULL,
            review_text TEXT NOT NULL,
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
            "SELECT * FROM places WHERE active = 1 AND name LIKE ? ORDER BY rating DESC",
            (f"%{query}%",),
        ).fetchall()
    else:
        places = conn.execute(
            "SELECT * FROM places WHERE active = 1 ORDER BY rating DESC"
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


@app.route("/place/<int:place_id>", methods=["GET", "POST"])
def place_details(place_id):
    conn = get_db()
    review_error = None
    review_form_text = ""

    try:
        place = conn.execute(
            "SELECT * FROM places WHERE id = ? AND active = 1",
            (place_id,),
        ).fetchone()

        if place is None:
            abort(404)

        if request.method == "POST":
            review_form_text = request.form.get("review_text", "")
            review_text = review_form_text.strip()

            if review_text:
                conn.execute(
                    "INSERT INTO reviews (place_id, review_text) VALUES (?, ?)",
                    (place_id, review_text),
                )
                conn.commit()
                return redirect(url_for("place_details", place_id=place_id))

            review_error = "Please enter a written review before submitting."

        reviews = conn.execute(
            "SELECT id, review_text FROM reviews WHERE place_id = ? ORDER BY id ASC",
            (place_id,),
        ).fetchall()

        return render_template(
            "place.html",
            place=place,
            reviews=reviews,
            review_error=review_error,
            review_form_text=review_form_text,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
