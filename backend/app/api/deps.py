"""Shared FastAPI dependencies."""

from __future__ import annotations

import sqlite3
from typing import Iterator

from .. import db


def get_conn() -> Iterator[sqlite3.Connection]:
    with db.connect() as conn:
        yield conn
