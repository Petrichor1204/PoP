import sqlite3
import json
from utils import validate_preferences, validate_decision

DB_NAME = "my_database.db"

def get_connection():
    return sqlite3.connect(DB_NAME)

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_title TEXT,
            item_type TEXT,
            verdict TEXT,
            confidence REAL,
            reasoning TEXT,
            potential_mismatches TEXT,
            created_at TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS preferences (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            likes TEXT,
            dislikes TEXT,
            pace TEXT,
            emotional_tolerance TEXT,
            goal TEXT,
            updated_at TEXT                     
        )
    ''')
    conn.commit()
    conn.close()
    

# ON CONFLICT is for updating existing values if the id is the same
# exclude is to assing to new values when there's conflict
def save_preferences(preferences):
    is_valid, error = validate_preferences(preferences)
    if not is_valid:
        print(f"Preferences invalid, not able to save: {error}")
        return False
    
    try:
        conn = get_connection()
        cursor = conn.cursor()
        with conn:
            cursor.execute(
                '''
            INSERT INTO preferences (
                id, likes, dislikes, pace, emotional_tolerance, goal, updated_at
                ) VALUES (1, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    likes = excluded.likes,
                    dislikes = excluded.dislikes,
                    pace = excluded.pace,
                    emotional_tolerance = excluded.emotional_tolerance,
                    goal = excluded.goal,
                    updated_at = excluded.updated_at

                ''',
                (
                    json.dumps(preferences["likes"]),
                    json.dumps(preferences["dislikes"]),
                    preferences["pace"],
                    preferences["emotional_tolerance"],
                    preferences["goal"],
                    preferences["updated_at"]
                )
            )
        return True
    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
        return False
    except Exception as e:
        print(f"Other error: {e}")
        return False
    finally:
        conn.close()

def get_preferences():
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM preferences WHERE id=1")
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None
    
    d = dict(row)
    try:
        d["likes"] = json.loads(d["likes"])
    except Exception:
        d["likes"] = []
    try:
        d["dislikes"] = json.loads(d["dislikes"])
    except Exception:
        d["dislikes"] = []

    return d

def delete_preferences():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM preferences where id=1")
    conn.commit()
    conn.close()

    return True

def save_decision(decision):
    """Validate and save a decision to the SQLite database using a transaction."""
    if not validate_decision(decision):
        print("Decision is invalid, not saving.")
        return False

    try:
        conn = get_connection()
        cursor = conn.cursor()
        # Serialize potential_mismatches to JSON string
        mismatches_json = json.dumps(decision["potential_mismatches"], ensure_ascii=False)
        with conn:
        # this ensures the connection closes even if the code crashes
            cursor.execute(
                '''
                INSERT INTO decisions (
                    item_title, item_type, verdict, confidence, reasoning, potential_mismatches, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    decision["item_title"],
                    decision["item_type"],
                    decision["verdict"],
                    decision["confidence"],
                    decision["reasoning"],
                    mismatches_json,
                    decision["created_at"]
                )
            )
        return True
    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
        return False
    except Exception as e:
        print(f"Other error: {e}")
        return False
    finally:
        conn.close()


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


def get_recent_decisions(limit=5):
    conn = sqlite3.connect(DB_NAME)
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


  
