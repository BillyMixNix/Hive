
from __future__ import annotations
import sqlite3, threading, uuid
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "workshop.db"
_lock = threading.RLock()

def now():
    return datetime.now(timezone.utc).isoformat()

def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c

def init_db():
    with _lock, connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS chats(
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            model TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(chat_id) REFERENCES chats(id)
        );
        CREATE TABLE IF NOT EXISTS memories(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            tags TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS usage(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT,
            provider TEXT,
            model TEXT,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            estimated_cost REAL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ledger(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            why TEXT DEFAULT '',
            risk TEXT DEFAULT 'low',
            approved INTEGER DEFAULT 0,
            details TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        """)
        c.commit()

def list_chats():
    with connect() as c:
        return [dict(x) for x in c.execute("SELECT * FROM chats ORDER BY updated_at DESC")]

def create_chat(title="New workshop"):
    cid = str(uuid.uuid4())
    t = now()
    with _lock, connect() as c:
        c.execute("INSERT INTO chats VALUES(?,?,?,?)", (cid,title,t,t))
        c.commit()
    return {"id":cid,"title":title,"created_at":t,"updated_at":t}

def get_messages(chat_id, limit=40):
    with connect() as c:
        rows = c.execute(
            "SELECT role,content,model,created_at FROM messages WHERE chat_id=? ORDER BY id DESC LIMIT ?",
            (chat_id, limit)
        ).fetchall()
    return [dict(x) for x in reversed(rows)]

def add_message(chat_id, role, content, model=None):
    t = now()
    with _lock, connect() as c:
        c.execute("INSERT INTO messages(chat_id,role,content,model,created_at) VALUES(?,?,?,?,?)",
                  (chat_id,role,content,model,t))
        c.execute("UPDATE chats SET updated_at=? WHERE id=?", (t,chat_id))
        # Auto-title from the first user message.
        n = c.execute("SELECT COUNT(*) n FROM messages WHERE chat_id=?", (chat_id,)).fetchone()["n"]
        if role == "user" and n <= 2:
            title = " ".join(content.strip().split())[:58] or "New workshop"
            c.execute("UPDATE chats SET title=? WHERE id=?", (title,chat_id))
        c.commit()

def list_memories():
    with connect() as c:
        return [dict(x) for x in c.execute("SELECT * FROM memories ORDER BY id DESC")]

def add_memory(text, tags=""):
    with _lock, connect() as c:
        cur = c.execute("INSERT INTO memories(text,tags,created_at) VALUES(?,?,?)",(text.strip(),tags.strip(),now()))
        c.commit()
        return cur.lastrowid

def delete_memory(mid):
    with _lock, connect() as c:
        c.execute("DELETE FROM memories WHERE id=?", (mid,))
        c.commit()

def add_usage(chat_id, provider, model, in_tok, out_tok, cost):
    with _lock, connect() as c:
        c.execute("""INSERT INTO usage(chat_id,provider,model,input_tokens,output_tokens,estimated_cost,created_at)
                     VALUES(?,?,?,?,?,?,?)""",
                  (chat_id,provider,model,int(in_tok or 0),int(out_tok or 0),float(cost or 0),now()))
        c.commit()

def usage_summary():
    with connect() as c:
        r = c.execute("""SELECT COALESCE(SUM(input_tokens),0) input_tokens,
                              COALESCE(SUM(output_tokens),0) output_tokens,
                              COALESCE(SUM(estimated_cost),0) estimated_cost,
                              COUNT(*) calls
                       FROM usage""").fetchone()
    return dict(r)


def chat_exists(chat_id):
    with connect() as c:
        r = c.execute("SELECT 1 FROM chats WHERE id=?", (chat_id,)).fetchone()
        return bool(r)

def add_ledger(action, why="", risk="low", approved=False, details=""):
    with _lock, connect() as c:
        c.execute("""INSERT INTO ledger(action,why,risk,approved,details,created_at)
                     VALUES(?,?,?,?,?,?)""",
                  (action, why, risk, 1 if approved else 0, details, now()))
        c.commit()

def list_ledger(limit=200):
    with connect() as c:
        return [dict(x) for x in c.execute(
            "SELECT * FROM ledger ORDER BY id DESC LIMIT ?", (int(limit),)
        )]

init_db()
