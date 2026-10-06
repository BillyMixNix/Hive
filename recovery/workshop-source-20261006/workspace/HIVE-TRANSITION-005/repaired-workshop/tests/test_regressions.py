
import pytest
from workshop import db

@pytest.fixture(autouse=True)
def init_schema():
    db.init_db()

def test_foreign_keys_enabled():
    with db.connect() as c:
        assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1

def test_chat_exists_false():
    assert db.chat_exists("definitely-not-a-real-chat") is False
