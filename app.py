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
# Initialize SocketIO with the app
socketio = SocketIO(app)

DB_FILE = "Kantinens_kunder.db"

# --- Scanner Process Management ---
# IMPORTANT: Replace 'scanner.py' with the actual path to your scanner script
# Ensure this path is correct relative to where you run app.py
SCANNER_SCRIPT_PATH = "scanner.py"
scanner_process = None # Variable to hold the scanner subprocess

def start_scanner_script():
    """Starts the scanner.py script in a separate process."""
    global scanner_process
    # Check if the process is running or has finished
    if scanner_process is None or scanner_process.poll() is not None:
        print(f"Attempting to start scanner script: {SCANNER_SCRIPT_PATH}")
        try:
            # Use sys.executable to ensure the script is run with the same Python interpreter
            # used for the Flask app.
            # stdout and stderr are redirected to PIPE so they don't clutter the main console
            # You could log these outputs if needed.
            # We use bufsize=1 for line buffering, which might help with real-time output processing
            scanner_process = subprocess.Popen([sys.executable, SCANNER_SCRIPT_PATH],
                                               stdout=subprocess.PIPE,
                                               stderr=subprocess.PIPE,
                                               text=True, # Decode output as text
                                               bufsize=1)
            print(f"Scanner script started successfully with PID: {scanner_process.pid}")

            # Optional: Start a thread to read scanner output if you want to display it
            # from threading import Thread
            # def read_scanner_output(process):
            #     for line in iter(process.stdout.readline, ''):
            #         print(f"SCANNER_OUT: {line.strip()}")
            #     for line in iter(process.stderr.readline, ''):
            #         print(f"SCANNER_ERR: {line.strip()}")
            # Thread(target=read_scanner_output, args=(scanner_process,), daemon=True).start()

        except FileNotFoundError:
            print(f"Error: Scanner script not found at '{SCANNER_SCRIPT_PATH}'. Make sure the path is correct.")
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
        print(f"Attempting to stop scanner script with PID: {scanner_process.pid}")
        try:
            scanner_process.terminate() # Send SIGTERM
            # Wait for process to terminate, with a timeout
            stdout, stderr = scanner_process.communicate(timeout=5)
            print("Scanner script stopped gracefully.")
            # print("Scanner stdout:\n", stdout) # Optional: print collected output
            # print("Scanner stderr:\n", stderr) # Optional: print collected errors
        except subprocess.TimeoutExpired:
            print("Scanner script did not terminate gracefully within timeout, killing.")
            scanner_process.kill() # Send SIGKILL
            stdout, stderr = scanner_process.communicate() # Collect output after kill
            # print("Scanner stdout:\n", stdout) # Optional: print collected output
            # print("Scanner stderr:\n", stderr) # Optional: print collected errors
        except Exception as e:
            print(f"Error stopping scanner script: {e}")
        finally:
            scanner_process = None
    else:
        print("Scanner script is not running.")

# Register stop_scanner_script to be called when the Flask app exits
# This ensures the scanner process is cleaned up when you stop the Flask server
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
    # Add some sample food data if the table is empty
    cursor.execute("SELECT COUNT(*) FROM foods")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO foods (name, image_url) VALUES (?, ?)", ('Frokost Ret', '')) # Add a placeholder food item
        conn.commit()

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

# Fetch food list (or just the current day's food)
# For simplicity, let's just return a static food item for now
def get_current_food_info():
     # In a real app, this would fetch based on the date or a selection
     # For now, return a placeholder
     return {
         "beskrivelse": "Dagens ret er en lækker pastasalat med kylling og pesto.",
         "allergener": ["Gluten", "Mælk", "Nødder"] # Example allergens
     }


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
    # Render index.html - this template will need JavaScript to handle SocketIO updates
    return render_template("index.html", tags=tags)

# Subscribe new UID page (This route is now primarily for manual registration if needed,
# as the scanner no longer redirects the browser)
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
        # The scanner will NOT trigger this redirect directly anymore
        return redirect(url_for("index"))

    # GET request: Show the subscription form
    # Check if UID already exists before showing the form
    user = get_tag_by_uid(uid)
    if user:
        flash(f"UID {uid} is already registered for {user[0]}.", "warning")
        return redirect(url_for("index"))

    # Render subscribe.html - this form is for manual registration via the browser
    return render_template("subscribe.html", uid=uid)


# Welcome page (This route is now primarily for manual access if needed,
# as the scanner no longer redirects the browser)
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
                    foods = get_foods() # Note: get_foods() is not implemented to return daily food
                    # Render welcome.html - this page is for manual access via the browser
                    # You might want to pass the daily food info here instead of all foods
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
    Returns a simple JSON response to scanner.py.
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
        # Return a simple JSON response as scanner.py doesn't use the redirect_url anymore
        return jsonify({"message": "No UID provided", "status": "error"}), 400

    print(f"Received scan request for UID: {uid}")

    # Emit processing status via SocketIO immediately
    socketio.emit('scan_result', {
        "authorized": False, # Not yet authorized
        "message": f"Processing UID: {uid}...",
        "name": None,
        "status": "processing",
        "uid": uid
    })

    user = get_tag_by_uid(uid)
    food_info = get_current_food_info() # Get daily food info

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
                        "food_info": food_info # Include food info
                    }
                    print(f"UID {uid} is authorized: {name}")
                    socketio.emit('scan_result', result_data) # Emit authorized status
                    # Return a simple JSON response
                    return jsonify({"message": f"Access Granted: {name}", "status": "authorized", "name": name}), 200
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
                    # Return a simple JSON response
                    return jsonify({"message": f"Subscription Expired for {name}", "status": "expired", "name": name}), 403 # Forbidden
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
                # Return a simple JSON response
                return jsonify({"message": f"Error: Invalid date format for {name}", "status": "error"}), 500 # Internal Server Error
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
            # Return a simple JSON response
            return jsonify({"message": f"Error: No subscription date for {name}", "status": "error"}), 500 # Internal Server Error


    else:
        # New card
        result_data = {
            "authorized": False,
            "name": None,
            "message": f"New card detected. Please register.",
            "status": "new",
            "uid": uid,
            # We don't redirect the browser anymore, but the UID is needed for registration
            "redirect_url": url_for('subscribe', uid=uid) # Kept for info, not used for redirect by scanner
        }
        print(f"UID {uid} is new.")
        socketio.emit('scan_result', result_data) # Emit new card status
        # Return a simple JSON response
        return jsonify({"message": "New card detected. Please register.", "status": "new", "uid": uid}), 404 # Not Found

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
    # Return a simple JSON response
    return jsonify({"status": "removed", "message": "Card removed"})

@app.route("/api/register", methods=["POST"])
def api_register():
    """
    Receives registration data (UID and name) from the frontend.
    Adds the user to the database and emits a SocketIO event.
    """
    data = request.json
    uid = data.get("uid")
    name = data.get("name")

    if not uid or not name:
        error_message = "Registration Error: Missing UID or name."
        print(error_message)
        socketio.emit('scan_result', {
            "authorized": False,
            "message": error_message,
            "name": None,
            "status": "error",
            "uid": uid
        })
        return jsonify({"message": error_message, "status": "error"}), 400

    print(f"Received registration request for UID: {uid}, Name: {name}")

    # Calculate expiry date 30 days from now
    valid_until = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

    if add_user(uid, name, valid_until):
        print(f"User {name} registered successfully with UID {uid}.")
        # Emit a success status, similar to a successful scan
        food_info = get_current_food_info() # Get daily food info
        result_data = {
            "authorized": True,
            "name": name,
            "message": f"Welcome {name}! Registration successful.",
            "status": "authorized", # Indicate successful registration and access
            "uid": uid,
            "food_info": food_info # Include food info
        }
        socketio.emit('scan_result', result_data) # Emit authorized status via SocketIO
        return jsonify({"message": "Registration successful", "status": "success", "name": name, "uid": uid}), 200
    else:
        error_message = f"Registration Error: UID {uid} already exists."
        print(error_message)
        # Emit an error status
        socketio.emit('scan_result', {
            "authorized": False,
            "message": error_message,
            "name": None,
            "status": "error",
            "uid": uid
        })
        return jsonify({"message": error_message, "status": "error"}), 409 # Conflict

# --- SocketIO Events ---

@socketio.on('connect')
def handle_connect():
    """Handler for new SocketIO client connections."""
    print('SocketIO client connected')
    # When a new client connects, emit a default 'waiting' status.
    socketio.emit('scan_result', {
        "authorized": False,
        "message": "Waiting for scan...",
        "name": None,
        "status": "waiting", # Indicate initial waiting state
        "uid": None
    })


@socketio.on('disconnect')
def handle_disconnect():
    """Handler for SocketIO client disconnections."""
    print('SocketIO client disconnected')


if __name__ == "__main__":
    # Start the scanner script before running the Flask-SocketIO app
    # This ensures the scanner is running when the web server starts
    start_scanner_script()

    # Use socketio.run instead of app.run to include the SocketIO server
    # host='0.0.0.0' makes it accessible externally (useful if scanner is on another machine)
    # host='127.0.0.1' restricts it to the local machine (safer for local development)
    print("Starting Flask-SocketIO server...")
    socketio.run(app, debug=True, host='127.0.0.1', port=5000)
