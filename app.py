from flask import Flask, render_template, request, redirect, flash, jsonify, url_for, send_from_directory
import sqlite3
from datetime import datetime, timedelta
import os

app = Flask(__name__)
app.secret_key = "supersecretkey"
DB_FILE = "Kantinens_kunder.db"

# Ensure DB exists and is initialized
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            nfc_id TEXT UNIQUE,
            name TEXT,
            subscription_valid_until TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS foods (
            id INTEGER PRIMARY KEY,
            name TEXT,
            image_url TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# Fetch tag owner
def get_tag_by_uid(uid):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT name, subscription_valid_until FROM users WHERE nfc_id = ?", (uid,))
    result = cursor.fetchone()
    conn.close()
    return result

# Fetch food list
def get_foods():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT name, image_url FROM foods")
    foods = cursor.fetchall()
    conn.close()
    return foods

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')

# Homepage
@app.route("/")
def index():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT nfc_id, name, subscription_valid_until FROM users")
    tags = cursor.fetchall()
    conn.close()
    return render_template("index.html", tags=tags)

# Subscribe new UID
@app.route("/subscribe/<uid>", methods=["GET", "POST"])
def subscribe(uid):
    if request.method == "POST":
        name = request.form["name"]
        valid_until = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")  # Default 30 days
        if valid_until:
            expiry = datetime.strptime(valid_until, "%Y-%m-%d")
        else:
            expiry = datetime.min  # Fails the expiration check

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (nfc_id, name, subscription_valid_until)
            VALUES (?, ?, ?)
        """, (uid, name, valid_until))
        conn.commit()
        conn.close()

        flash(f"Welcome {name}, your subscription is now active!", "success")
        return redirect(url_for("index"))

    return render_template("subscribe.html", uid=uid)


# Welcome and show food if known UID
@app.route("/welcome/<uid>")
def welcome(uid):
    user = get_tag_by_uid(uid)
    if user:
        name, valid_until = user
        if valid_until and datetime.strptime(valid_until, "%Y-%m-%d") >= datetime.now():
            foods = get_foods()
            return render_template("welcome.html", name=name, foods=foods)
        else:
            flash("Your subscription has expired.", "danger")
            return redirect(url_for("index"))
    else:
        flash("Unknown user.", "danger")
        return redirect(url_for("index"))


# API endpoint for scanner to check UID
card_present = False  # Global flag

@app.route("/api/scan", methods=["POST"])
def api_scan():
    global card_present
    data = request.json
    uid = data.get("uid")

    user = get_tag_by_uid(uid)
    if user:
        name, valid_until = user
        if valid_until and datetime.strptime(valid_until, "%Y-%m-%d") >= datetime.now():
            card_present = True
            return jsonify({
                "status": "authorized",
                "name": name,
                "redirect_url": f"/welcome/{uid}"
            }), 200
        else:
            return jsonify({
                "status": "expired",
                "name": name
            }), 403
    else:
        return jsonify({
            "status": "new",
            "redirect_url": f"/subscribe/{uid}"
        }), 404

@app.route("/api/remove", methods=["POST"])
def api_remove():
    global card_present
    card_present = False
    return jsonify({"status": "removed"})

@app.route("/api/present")
def api_present():
    return jsonify({"present": card_present})



if __name__ == "__main__":
    app.run(debug=True)