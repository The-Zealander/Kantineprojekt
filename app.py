# app.py
from flask import Flask, render_template, request, redirect, flash, jsonify, url_for, send_from_directory
from flask_socketio import SocketIO, emit
import sqlite3
from datetime import datetime, timedelta
import os
import time
import subprocess # Import subprocess
import sys # Import sys to get the Python executable path
import atexit # Import atexit for cleanup

app = Flask(__name__)
app.config['SECRET_KEY'] = 'supersecretkey'
socketio = SocketIO(app)

DB_FILE = "Kantinens_kunder.db"

# --- Scanner Process Management ---
# IMPORTANT: Replace 'scanner.py' with the actual path to your scanner script
SCANNER_SCRIPT_PATH = "scanner.py"
scanner_process = None # Variable to hold the scanner subprocess

def start_scanner_script():
    """Starts the scanner.py script in a separate process."""
    global scanner_process
    if scanner_process is None or scanner_process.poll() is not None:
        print(f"Starting scanner script: {SCANNER_SCRIPT_PATH}")
        try:
            # Use sys.executable to ensure the script is run with the same Python interpreter
            # used for the Flask app.
            # stdout and stderr are redirected to PIPE so they don't clutter the main console
            # You could log these outputs if needed.
            scanner_process = subprocess.Popen([sys.executable, SCANNER_SCRIPT_PATH],
                                               stdout=subprocess.PIPE,
                                               stderr=subprocess.PIPE)
            print(f"Scanner script started with PID: {scanner_process.pid}")
        except FileNotFoundError:
            print(f"Error: Scanner script not found at {SCANNER_SCRIPT_PATH}")
            scanner_process = None
        except Exception as e:
            print(f"Error starting scanner script: {e}")
            scanner_process = None
    else:
        print("Scanner script is already running.")

def stop_scanner_script():
    """Stops the scanner.py script process."""
    global scanner_process
    if scanner_process is not None and scanner_process.poll() is None:
        print(f"Stopping scanner script with PID: {scanner_process.pid}")
        try:
            scanner_process.terminate() # or scanner_process.kill() for forceful termination
            scanner_process.wait(timeout=5) # Wait for process to terminate
            print("Scanner script stopped.")
        except subprocess.TimeoutExpired:
            print("Scanner script did not terminate gracefully, killing.")
            scanner_process.kill()
        except Exception as e:
            print(f"Error stopping scanner script: {e}")
        finally:
            scanner_process = None
    else:
        print("Scanner script is not running.")

# Register stop_scanner_script to be called when the Flask app exits
atexit.register(stop_scanner_script)


# --- Database Functions ---

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

# Add new user
def add_user(nfc_id, name, subscription_valid_until):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO users (nfc_id, name, subscription_valid_until)
            VALUES (?, ?, ?)
        """, (nfc_id, name, subscription_valid_until))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        # UID already exists
        return False
    finally:
        conn.close()

# Update user name
def update_user_name(tag_id, new_name):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET name = ? WHERE id = ?", (new_name, tag_id))
    conn.commit()
    conn.close()

# Initialize the database when the app starts
init_db()

# --- Flask Routes ---

# Favicon route
@app.route('/favicon.ico')
def favicon():
    # Assuming you have a static folder with a favicon.ico file
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')

# Homepage - Displays user list and the dynamic status area
@app.route("/", methods=["GET", "POST"])
def index():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    if request.method == "POST":
        if 'add' in request.form:
            # Handle adding a new tag from the debug panel
            nfc_id = request.form["nfc_id"]
            name = request.form["name"]
            valid_until = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d") # Default 30 days

            if add_user(nfc_id, name, valid_until):
                flash(f"Tag {nfc_id} registered for {name}!", "success")
            else:
                flash(f"Error: Tag {nfc_id} already exists.", "danger")

        elif 'update' in request.form:
            # Handle updating an existing tag from the debug panel
            tag_id = request.form["tag_id"]
            new_name = request.form["new_name"]
            update_user_name(tag_id, new_name)
            flash("Tag updated successfully!", "success")

        # Redirect to GET request to avoid form resubmission on refresh
        return redirect(url_for('index'))

    # GET request: Display the page
    cursor.execute("SELECT id, nfc_id, name FROM users") # Fetch id for update form
    tags = cursor.fetchall()
    conn.close()
    return render_template("index.html", tags=tags)

# Subscribe new UID page (triggered by scanner.py redirect)
@app.route("/subscribe/<uid>", methods=["GET", "POST"])
def subscribe(uid):
    if request.method == "POST":
        name = request.form["name"]
        # Calculate expiry date 30 days from now
        valid_until = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

        if add_user(uid, name, valid_until):
             flash(f"Welcome {name}, your subscription is now active until {valid_until}!", "success")
        else:
             # This case should ideally be caught before showing the form, but handle defensively
             flash(f"Error: UID {uid} already exists.", "danger")

        # Redirect back to the main page after subscription
        return redirect(url_for("index"))

    # GET request: Show the subscription form
    # Check if UID already exists before showing the form
    user = get_tag_by_uid(uid)
    if user:
        flash(f"UID {uid} is already registered for {user[0]}.", "warning")
        return redirect(url_for("index"))

    return render_template("subscribe.html", uid=uid)


# Welcome page (triggered by scanner.py redirect for authorized users)
@app.route("/welcome/<uid>")
def welcome(uid):
    user = get_tag_by_uid(uid)
    if user:
        name, valid_until_str = user
        # Check if valid_until_str is not None and is a valid date string
        if valid_until_str:
            try:
                valid_until = datetime.strptime(valid_until_str, "%Y-%m-%d")
                if valid_until >= datetime.now():
                    foods = get_foods()
                    return render_template("welcome.html", name=name, foods=foods)
                else:
                    flash(f"Your subscription for {name} expired on {valid_until_str}.", "danger")
                    return redirect(url_for("index"))
            except ValueError:
                 # Handle case where date string is invalid
                flash(f"Invalid subscription date format for user {name}.", "danger")
                return redirect(url_for("index"))
        else:
             # Handle case where valid_until is NULL in DB
            flash(f"No subscription date found for user {name}.", "danger")
            return redirect(url_for("index"))

    else:
        flash("Unknown user.", "danger")
        return redirect(url_for("index"))


# --- API Endpoints for Scanner ---

@app.route("/api/scan", methods=["POST"])
def api_scan():
    """
    Receives scan data from scanner.py.
    Processes the UID, determines status, and emits a SocketIO event.
    Returns a response to scanner.py for potential browser redirect.
    """
    data = request.json
    uid = data.get("uid")

    if not uid:
        # Emit error status via SocketIO
        socketio.emit('scan_result', {
            "authorized": False,
            "message": "Scan Error: No UID received.",
            "name": None,
            "status": "error",
            "uid": None
        })
        print("Received scan request with no UID.")
        return jsonify({"message": "No UID provided"}), 400

    print(f"Received scan request for UID: {uid}")

    # Emit processing status via SocketIO
    socketio.emit('scan_result', {
        "authorized": False, # Not yet authorized
        "message": f"Processing UID: {uid}...",
        "name": None,
        "status": "processing",
        "uid": uid
    })

    user = get_tag_by_uid(uid)

    if user:
        name, valid_until_str = user
        # Check if valid_until_str is not None and is a valid date string
        if valid_until_str:
            try:
                valid_until = datetime.strptime(valid_until_str, "%Y-%m-%d")
                if valid_until >= datetime.now():
                    # Authorized user
                    result_data = {
                        "authorized": True,
                        "name": name,
                        "message": f"Access Granted: {name}",
                        "status": "authorized",
                        "uid": uid,
                        "redirect_url": url_for('welcome', uid=uid) # Redirect to welcome page
                    }
                    print(f"UID {uid} is authorized: {name}")
                    socketio.emit('scan_result', result_data) # Emit authorized status
                    return jsonify(result_data), 200
                else:
                    # Subscription expired
                    result_data = {
                        "authorized": False,
                        "name": name,
                        "message": f"Subscription Expired for {name}.",
                        "status": "expired",
                        "uid": uid
                    }
                    print(f"UID {uid} subscription expired: {name}")
                    socketio.emit('scan_result', result_data) # Emit expired status
                    return jsonify(result_data), 403 # Forbidden
            except ValueError:
                 # Handle invalid date format in DB
                result_data = {
                    "authorized": False,
                    "name": name,
                    "message": f"Error: Invalid date format for {name}.",
                    "status": "error",
                    "uid": uid
                }
                print(f"UID {uid} has invalid date format.")
                socketio.emit('scan_result', result_data) # Emit error status
                return jsonify(result_data), 500 # Internal Server Error
        else:
            # Handle NULL valid_until in DB
            result_data = {
                "authorized": False,
                "name": name,
                "message": f"Error: No subscription date for {name}.",
                "status": "error",
                "uid": uid
            }
            print(f"UID {uid} has no subscription date.")
            socketio.emit('scan_result', result_data) # Emit error status
            return jsonify(result_data), 500 # Internal Server Error

    else:
        # New card
        result_data = {
            "authorized": False,
            "name": None,
            "message": f"New card detected. Please register.",
            "status": "new",
            "uid": uid,
            "redirect_url": url_for('subscribe', uid=uid) # Redirect to subscribe page
        }
        print(f"UID {uid} is new.")
        socketio.emit('scan_result', result_data) # Emit new card status
        return jsonify(result_data), 404 # Not Found

@app.route("/api/remove", methods=["POST"])
def api_remove():
    """
    Receives notification from scanner.py when a card is removed.
    Emits a SocketIO event to update the frontend status.
    """
    print("Card removed notification received.")
    # Emit removed status via SocketIO
    socketio.emit('scan_result', {
        "authorized": False,
        "message": "Card removed. Waiting for scan...",
        "name": None,
        "status": "removed", # Use a 'removed' status
        "uid": None
    })
    return jsonify({"status": "removed"})


# --- SocketIO Events ---

@socketio.on('connect')
def handle_connect():
    print('Client connected')
    # Optionally, emit the current status when a new client connects
    # This requires storing the last status server-side, similar to the polling approach
    # For simplicity here, we'll just log the connection.
    # You could add logic here to send the last known state if needed.

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')


if __name__ == "__main__":
    # Start the scanner script before running the Flask-SocketIO app
    start_scanner_script()

    # Use socketio.run instead of app.run
    # host='0.0.0.0' makes it accessible externally (useful if scanner is on another machine)
    # host='127.0.0.1' restricts it to the local machine
    socketio.run(app, debug=True, host='127.0.0.1', port=5000)

