"""Pytest bootstrap: pin the app environment before any ``api`` import.

``api.database`` builds its SQLAlchemy engine at import time from
``DATABASE_URL``. Pytest collects test modules alphabetically, so without this
file whichever module imports ``api`` first decides whether the engine exists
at all -- the auth suite then failed only when run with the other suites.
A conftest runs before any test module, so the URL is always set in time.

The tests are fully mocked/isolated; pointing DATABASE_URL at a throwaway
SQLite file guarantees they can never touch a real Postgres database.
"""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test_auth.db"
os.environ["JWT_SECRET"] = "test-secret"
