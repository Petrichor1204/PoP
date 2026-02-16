import sqlite3

DB_NAME = "my_database.db"

def get_connection():
    return sqlite3.connect(DB_NAME)

def get_decision_by_id(decision_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM decisions WHERE id = ?",
        (decision_id,)
    )

    row = cursor.fetchone()
    conn.close()

    return row


import json
def get_recent_decisions(limit=5):
    conn = sqlite3.connect('my_database.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM decisions ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    decisions = []
    for row in rows:
        d = dict(row)
        d["potential_mismatches"] = json.loads(d["potential_mismatches"])
        decisions.append(d)

    conn.close()
    return decisions


  
