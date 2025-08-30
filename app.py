# app.py
import os, sqlite3, json
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from datetime import date, datetime
from model import predict_for_user, train_global_model, SEQ_LEN
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "dev-secret-for-demo"  # replace in production
DB = "data/microhabits.db"
MODEL_PATH = "models/global_model.h5"

# Helpers
def db_connect():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def get_user(username):
    conn = db_connect()
    cur = conn.execute("SELECT id, username FROM users WHERE username=?", (username,))
    row = cur.fetchone()
    conn.close()
    return row

def create_user(username):
    conn = db_connect()
    cur = conn.execute("INSERT OR IGNORE INTO users (username) VALUES (?)", (username,))
    conn.commit()
    cur = conn.execute("SELECT id FROM users WHERE username=?", (username,))
    uid = cur.fetchone()[0]
    conn.close()
    return uid

def get_user_habits(user_id):
    conn = db_connect()
    rows = conn.execute("SELECT name, is_custom FROM habits WHERE user_id=?", (user_id,)).fetchall()
    conn.close()
    return [r["name"] for r in rows]

@app.route("/", methods=["GET","POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username").strip()
        if not username:
            flash("Enter a username")
            return redirect(url_for("login"))
        # create or get user
        uid = create_user(username)
        session['user_id'] = uid
        session['username'] = username
        return redirect(url_for("dashboard"))
    return render_template("login.html")

@app.route("/dashboard")
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for("login"))
    uid = session['user_id']
    habits = get_user_habits(uid)
    # for each habit predict skip risk for "today morning" by default
    today = date.today().isoformat()
    results = []
    for h in habits:
        try:
            p = predict_for_user(uid, h, as_of_date=today, time_of_day="morning", model_path=MODEL_PATH)
        except Exception as e:
            p = 0.1
        results.append({"habit":h, "skip_prob": round(p,3)})
    # sort descending risk
    results = sorted(results, key=lambda x: x["skip_prob"], reverse=True)
    return render_template("dashboard.html", username=session.get("username"), results=results)

@app.route("/log", methods=["POST"])
def log():
    if 'user_id' not in session:
        return redirect(url_for("login"))
    uid = session['user_id']
    habit = request.form.get("habit")
    date_str = request.form.get("date") or date.today().isoformat()
    tod = request.form.get("time_of_day") or "morning"
    completed = int(request.form.get("completed", "0"))
    conn = db_connect()
    conn.execute("INSERT INTO logs (user_id, habit, date, time_of_day, completed) VALUES (?,?,?,?,?)",
                 (uid, habit, date_str, tod, completed))
    conn.commit()
    conn.close()
    flash("Logged.")
    return redirect(url_for("dashboard"))

@app.route("/add_habit", methods=["GET","POST"])
def add_habit():
    if 'user_id' not in session:
        return redirect(url_for("login"))
    if request.method == "POST":
        name = request.form.get("name").strip()
        if not name:
            flash("Enter habit name")
            return redirect(url_for("add_habit"))
        conn = db_connect()
        conn.execute("INSERT INTO habits (user_id, name, is_custom) VALUES (?,?,1)", (session['user_id'], name))
        conn.commit()
        conn.close()
        flash("Habit added.")
        return redirect(url_for("dashboard"))
    return render_template("add_habit.html")

@app.route("/retrain", methods=["POST"])
def retrain():
    # retrain global model (slow) - in demo it's synchronous
    try:
        model_file = train_global_model(db_path=DB, model_path=MODEL_PATH)
        flash("Retrained global model.")
    except Exception as e:
        flash(f"Retrain failed: {e}")
    return redirect(url_for("dashboard"))

@app.route("/api/history/<habit>")
def api_history(habit):
    if 'user_id' not in session:
        return jsonify([])
    uid = session['user_id']
    conn = db_connect()
    rows = conn.execute("SELECT date, completed FROM logs WHERE user_id=? AND habit=? ORDER BY date", (uid, habit)).fetchall()
    conn.close()
    dates = [r["date"] for r in rows]
    completed = [r["completed"] for r in rows]
    return jsonify({"dates": dates, "completed": completed})

if __name__ == "__main__":
    # ensure model exists
    if not os.path.exists(MODEL_PATH):
        print("No global model found — training now (this may take a few minutes)...")
        train_global_model(db_path=DB, model_path=MODEL_PATH)
    app.run(debug=True, port=5000)
