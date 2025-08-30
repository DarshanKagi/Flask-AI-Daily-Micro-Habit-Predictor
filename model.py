# model.py
import os
import numpy as np
import pandas as pd
from tensorflow.keras.models import Model, load_model
from tensorflow.keras.layers import Input, LSTM, Dense, Concatenate, Flatten
from tensorflow.keras.optimizers import Adam
from sklearn.preprocessing import StandardScaler, OneHotEncoder
import pickle
from collections import defaultdict
import sqlite3
from datetime import datetime, date, timedelta

MODELS_DIR = "models"
os.makedirs(MODELS_DIR, exist_ok=True)

SEQ_LEN = 7

# Helpers to fetch data from SQLite
def fetch_all_logs(db_path="data/microhabits.db"):
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("SELECT user_id, habit, date, time_of_day, completed FROM logs", conn,
                           parse_dates=["date"])
    conn.close()
    return df

# Build dataset for training global model
def build_dataset(df):
    # df: columns user_id, habit, date (datetime), time_of_day, completed
    df = df.sort_values(["user_id","habit","date"])
    X_seq = []
    X_tab = []
    y = []
    habit_list = df['habit'].unique().tolist()
    habit_index = {h:i for i,h in enumerate(habit_list)}
    for (uid, habit), group in df.groupby(["user_id","habit"]):
        comp = group['completed'].tolist()
        times = group['time_of_day'].tolist()
        dates = pd.to_datetime(group['date']).dt.date.tolist()
        for i in range(SEQ_LEN, len(comp)):
            seq = comp[i-SEQ_LEN:i]
            target = 1 - comp[i]  # skip risk = 1 - completed
            # tabular features for day i (we use day-of-week of target day, habit one-hot, time_of_day)
            dow = dates[i].weekday()
            time_of_day = times[i]
            tod_vec = [1 if time_of_day == t else 0 for t in ["morning","afternoon","evening"]]
            habit_vec = [0]*len(habit_list)
            habit_vec[habit_index[habit]] = 1
            # streak length up to previous day
            streak = 0
            for v in reversed(seq):
                if v == 1:
                    streak += 1
                else:
                    break
            X_seq.append(np.array(seq).reshape((SEQ_LEN,1)))
            X_tab.append([streak, dow] + tod_vec + habit_vec)
            y.append(target)
    X_seq = np.array(X_seq, dtype=np.float32)
    X_tab = np.array(X_tab, dtype=np.float32)
    y = np.array(y, dtype=np.float32)
    return X_seq, X_tab, y, habit_list

def build_model(seq_len=SEQ_LEN, tab_dim=None):
    # sequence branch
    seq_in = Input(shape=(seq_len,1), name="seq_in")
    x = LSTM(32, name="lstm")(seq_in)
    x = Dense(16, activation="relu")(x)
    # tabular branch
    tab_in = Input(shape=(tab_dim,), name="tab_in")
    t = Dense(64, activation="relu")(tab_in)
    t = Dense(16, activation="relu")(t)
    # combine
    merged = Concatenate()([x,t])
    m = Dense(32, activation="relu")(merged)
    out = Dense(1, activation="sigmoid", name="skip_prob")(m)
    model = Model([seq_in, tab_in], out)
    model.compile(optimizer=Adam(1e-3), loss="binary_crossentropy", metrics=["AUC"])
    return model

# Train global model on df and save model + scaler + habit_list
def train_global_model(db_path="data/microhabits.db", model_path=os.path.join(MODELS_DIR,"global_model.h5")):
    df = fetch_all_logs(db_path)
    X_seq, X_tab, y, habit_list = build_dataset(df)
    # scale X_tab (streak, dow, tod, habit one-hot)
    scaler = StandardScaler()
    X_tab_scaled = scaler.fit_transform(X_tab)
    model = build_model(seq_len=SEQ_LEN, tab_dim=X_tab_scaled.shape[1])
    model.fit([X_seq, X_tab_scaled], y, epochs=10, batch_size=128, validation_split=0.1, verbose=2)
    model.save(model_path)
    with open(os.path.join(MODELS_DIR, "scaler.pkl"), "wb") as f:
        pickle.dump({"scaler":scaler, "habits":habit_list}, f)
    print("Saved global model and scaler.")
    return model_path

# Predict for given user and habit using last SEQ_LEN logs
def predict_for_user(user_id, habit, as_of_date=None, time_of_day="morning", db_path="data/microhabits.db", model_path=os.path.join(MODELS_DIR,"global_model.h5")):
    if as_of_date is None:
        as_of_date = date.today()
    else:
        as_of_date = pd.to_datetime(as_of_date).date()
    # load scaler & habit list
    with open(os.path.join(MODELS_DIR, "scaler.pkl"), "rb") as f:
        info = pickle.load(f)
    scaler = info["scaler"]
    habit_list = info["habits"]
    # get last SEQ_LEN completions for that user/habit
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("SELECT date, completed FROM logs WHERE user_id=? AND habit=? ORDER BY date DESC LIMIT ?",
                           conn, params=(user_id, habit, SEQ_LEN))
    conn.close()
    seq = [0]*(SEQ_LEN - len(df)) + df['completed'].tolist()[::-1] if len(df) < SEQ_LEN else df['completed'].tolist()[::-1]
    seq_arr = np.array(seq, dtype=np.float32).reshape((1, SEQ_LEN, 1))
    # tab features
    dow = as_of_date.weekday()
    tod_vec = [1 if time_of_day == t else 0 for t in ["morning","afternoon","evening"]]
    habit_vec = [0]*len(habit_list)
    if habit in habit_list:
        habit_vec[habit_list.index(habit)] = 1
    else:
        # unknown habit: append zero vector (scaler expects consistent size) -- but scaler was fit with global habit count
        pass
    streak = 0
    for v in reversed(seq):
        if v == 1:
            streak += 1
        else:
            break
    tab = np.array([[streak, dow] + tod_vec + habit_vec], dtype=np.float32)
    tab_scaled = scaler.transform(tab)
    model = load_model(model_path)
    prob = float(model.predict([seq_arr, tab_scaled], verbose=0)[0,0])
    # prob is modeled as skip risk (since target=1 - completed)
    return prob

# Example quick train call guard
if __name__ == "__main__":
    print("Training global model on generated seed DB...")
    train_global_model()
