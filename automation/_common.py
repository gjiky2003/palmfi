"""Shared helpers for automation modules."""
import os
import json
import sqlite3


def get_db():
    db_path = os.path.join(os.path.dirname(__file__), '..', 'platform', 'palmfi.db')
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def get_settings(*keys, default=''):
    path = os.path.join(os.path.dirname(__file__), '..', 'launch', 'settings.json')
    try:
        with open(path) as f:
            d = json.load(f)
        for k in keys:
            d = d[k]
        return d or default
    except Exception:
        env_key = '_'.join(keys).upper()
        return os.getenv(env_key, default)
