# generate_data.py
import os, sqlite3, random
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

OUT_DIR = "data"
os.makedirs(OUT_DIR, exist_ok=True)

USERS = [f"user_{i+1}" for i in range(20)]
HABITS = ["drink_water","stretch","walk_5min","read_5min","meditate","sleep_early","journal"]

start_date = datetime.utcnow().date() - timedelta(days=29)
rows = []
random.seed(42)
np.random.seed(42)

for u_idx, user in enumerate(USERS):
    # user-specific baseline skip probabilities
    base_skip = 0.1 + (u_idx % 5) * 0.08  # varied baseline
    for day_off in range(30):
        date = start_date + timedelta(days=day_off)
        dow = date.weekday()
        for habit in HABITS:
            # slight habit-specific difficulty
            habit_factor = {
                "drink_water": 0.05,
                "stretch": 0.12,
                "walk_5min": 0.18,
                "read_5min": 0.14,
                "meditate": 0.16,
                "sleep_early": 0.2,
                "journal": 0.15
            }[habit]
            # time of day randomly assigned
            tod = random.choices(["morning","afternoon","evening"], weights=[0.5,0.25,0.25])[0]
            # weekend effect
            weekend = 1 if dow >= 5 else 0
            skip_p = min(0.85, base_skip + habit_factor + (0.08 if weekend else 0) + random.uniform(-0.05,0.06))
            completed = 0 if random.random() < skip_p else 1
            rows.append({
                "user": user,
                "date": date.isoformat(),
                "habit": habit,
                "time_of_day": tod,
                "completed": int(completed)
            })

df = pd.DataFrame(rows)
seed_csv = os.path.join(OUT_DIR, "seed_data.csv")
df.to_csv(seed_csv, index=False)
print(f"Saved seed CSV to {seed_csv} ({len(df)} rows)")

# Create SQLite DB and seed tables
DB_PATH = os.path.join(OUT_DIR, "microhabits.db")
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()
c.executescript("""
CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE);
CREATE TABLE habits (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, is_custom INTEGER DEFAULT 0);
CREATE TABLE logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, habit TEXT, date TEXT, time_of_day TEXT, completed INTEGER);
""")
conn.commit()

# insert users and logs
for user in USERS:
    c.execute("INSERT INTO users (username) VALUES (?)", (user,))
conn.commit()

# map username to id
user_map = {row[0]: row[0] for row in []}
c.execute("SELECT id, username FROM users")
user_map = {username: uid for uid, username in c.fetchall()}

for _, r in df.iterrows():
    uid = user_map[r["user"]]
    c.execute("INSERT INTO habits (user_id, name, is_custom) VALUES (?,?,0)", (uid, r["habit"]))
    break  # avoid duplicates for seeding habits; we will insert logs directly
# remove that extra insert; re-create habits per user below
c.execute("DELETE FROM habits")
conn.commit()

for username, uid in user_map.items():
    for habit in HABITS:
        c.execute("INSERT INTO habits (user_id, name, is_custom) VALUES (?,?,0)", (uid, habit))
conn.commit()

for _, r in df.iterrows():
    uid = user_map[r["user"]]
    c.execute("INSERT INTO logs (user_id, habit, date, time_of_day, completed) VALUES (?,?,?,?,?)",
              (uid, r["habit"], r["date"], r["time_of_day"], int(r["completed"])))
conn.commit()
conn.close()
print(f"Seed SQLite DB created at {DB_PATH}")
