"""Pruebas de la configuracion PostgreSQL sin abrir conexiones reales."""
import unittest
from unittest.mock import patch

from app.config import database_url


class DatabaseUrlTests(unittest.TestCase):
    def test_database_url_has_priority_and_preserves_neon_parameters(self):
        environment = {
            "DATABASE_URL": (
                "postgres://example:secret@example.neon.tech/neondb"
                "?sslmode=require&channel_binding=require"
            ),
            "PGPASSWORD": "ignored",
        }
        with patch.dict("os.environ", environment, clear=True):
            url = database_url()

        self.assertEqual(url.drivername, "postgresql+psycopg2")
        self.assertEqual(url.host, "example.neon.tech")
        self.assertEqual(url.database, "neondb")
        self.assertEqual(url.query["sslmode"], "require")
        self.assertEqual(url.query["channel_binding"], "require")

    def test_pg_variables_are_the_fallback(self):
        environment = {
            "PGHOST": "localhost",
            "PGPORT": "5432",
            "PGDATABASE": "j2f_monitoreo",
            "PGUSER": "postgres",
            "PGPASSWORD": "example-only",
        }
        with patch.dict("os.environ", environment, clear=True):
            url = database_url()

        self.assertEqual(url.drivername, "postgresql+psycopg2")
        self.assertEqual(url.host, "localhost")
        self.assertEqual(url.port, 5432)
        self.assertEqual(url.database, "j2f_monitoreo")

    def test_missing_credentials_do_not_leak_a_connection_value(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "PGPASSWORD o DATABASE_URL"):
                database_url()

    def test_malformed_database_url_is_not_repeated_in_the_error(self):
        invalid_value = "not-a-database-url-with-private-content"
        with patch.dict("os.environ", {"DATABASE_URL": invalid_value}, clear=True):
            with self.assertRaises(RuntimeError) as raised:
                database_url()

        self.assertNotIn(invalid_value, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
