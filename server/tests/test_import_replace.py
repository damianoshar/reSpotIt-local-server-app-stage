"""CSV import mirror-mode tests (mocked DB, no Postgres/Spotify)."""
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from api.routers import import_csv as routes


class _FakeCursor:
    """Records statements; answers the two RETURNING shapes the route uses."""

    def __init__(self, delete_rowcount=0):
        self.calls = []
        self._queued = []
        self.rowcount = delete_rowcount
        self.closed = False

    def execute(self, sql, params=None):
        # psycopg2 raises on use-after-close; a fake that does not reproduce
        # that hid a real bug where the mirror DELETE ran after the cursor's
        # `with` block had already exited.
        if self.closed:
            raise RuntimeError("cursor already closed")
        norm = " ".join(sql.split())
        self.calls.append((norm, params))
        if "RETURNING id, (xmax = 0)" in norm:
            self._queued.append((1, True))
        elif "RETURNING id" in norm:
            self._queued.append((1,))

    def fetchone(self):
        return self._queued.pop(0)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True
        return False

    def statements(self, needle):
        return [c for c in self.calls if needle in c[0]]


class _FakeConn:
    def __init__(self, cursor):
        self.autocommit = True
        self._cursor = cursor
        self.closed = False

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True


HEADER = "id,title,artist,year,genre,image_url,added_at"
VALID = "\n".join([
    HEADER,
    "a1,Album One,Artist A,2020,Rock,http://img/1,2020-01-01",
    "a2,Album Two,Artist B,2021,Pop,http://img/2,2021-01-01",
])
INVALID = "\n".join([HEADER, ",,,"])


class ImportMirrorTests(unittest.TestCase):
    def _run(self, body, cursor=None):
        cursor = cursor or _FakeCursor()
        conn = _FakeConn(cursor)
        patches = [
            patch.object(routes, "DATABASE_URL", "postgresql://test/db"),
            patch.object(routes, "wait_for_db"),
            patch.object(routes, "run_migrations"),
            patch.object(routes.psycopg2, "connect", return_value=conn),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        result = routes.import_csv(
            body, user=SimpleNamespace(id=str(uuid.uuid4())),
        )
        return result, cursor

    def test_replace_removes_albums_absent_from_the_payload(self):
        result, cursor = self._run(
            routes.ImportBody(csv_content=VALID, replace=True),
        )
        deletes = cursor.statements("DELETE FROM albums")
        self.assertEqual(len(deletes), 1)
        self.assertEqual(result["imported"], 2)
        self.assertIn("removed", result)
        # The keep-list is exactly what the payload carried.
        self.assertEqual(sorted(deletes[0][1][1]), ["a1", "a2"])
        self.assertEqual(len(cursor.statements("DELETE FROM artists")), 1)

    def test_merge_never_deletes(self):
        result, cursor = self._run(routes.ImportBody(csv_content=VALID))
        self.assertEqual(result["removed"], 0)
        self.assertEqual(result["imported"], 2)
        self.assertEqual(cursor.statements("DELETE FROM albums"), [])
        self.assertEqual(cursor.statements("DELETE FROM artists"), [])

    def test_replace_with_no_valid_rows_never_wipes_the_library(self):
        result, cursor = self._run(
            routes.ImportBody(csv_content=INVALID, replace=True),
        )
        self.assertEqual(result["removed"], 0)
        self.assertEqual(cursor.statements("DELETE FROM albums"), [])
        self.assertTrue(any("Mirror skipped" in e for e in result["errors"]))

    def test_empty_csv_returns_before_touching_the_db(self):
        result, cursor = self._run(
            routes.ImportBody(csv_content="   \n\n", replace=True),
        )
        self.assertEqual(result["errors"], ["CSV file is empty"])
        self.assertEqual(cursor.calls, [])


if __name__ == "__main__":
    unittest.main()
