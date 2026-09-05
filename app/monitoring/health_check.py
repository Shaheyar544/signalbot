from __future__ import annotations

import sqlite3


def database_available(path: str) -> bool:
    try:
        connection = sqlite3.connect(path if path == ":memory:" else f"file:{path}?mode=rw", uri=path != ":memory:")
        connection.execute("SELECT 1").fetchone()
        connection.close()
        return True
    except sqlite3.Error:
        return False
