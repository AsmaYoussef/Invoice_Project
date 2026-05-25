"""Shared MySQL connection helper for api.py and api_admin.py."""
from __future__ import annotations

import mysql.connector

DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 3307,
    "user": "root",
    "password": "admin",
    "database": "diva_demo",
    "auth_plugin": "mysql_native_password",
}


def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)
