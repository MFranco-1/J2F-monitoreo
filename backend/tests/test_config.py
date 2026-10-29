"""Pruebas de la configuracion PostgreSQL sin abrir conexiones reales."""
import unittest
from unittest.mock import patch

from app.config import database_url, get_config


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


class ConfigurationSafetyTests(unittest.TestCase):
    def test_development_keys_are_not_public_constants_and_are_stable_in_process(self):
        with patch.dict('os.environ', {}, clear=True):
            first, second = get_config('testing'), get_config('testing')
        self.assertGreaterEqual(len(first.JWT_SECRET_KEY), 32)
        self.assertNotEqual(first.SECRET_KEY, first.JWT_SECRET_KEY)
        self.assertEqual(first.JWT_SECRET_KEY, second.JWT_SECRET_KEY)
        self.assertNotIn('cambiar-en-produccion', first.JWT_SECRET_KEY)

    def test_production_rejects_missing_placeholder_short_or_reused_secrets(self):
        base = {'DATABASE_URL': 'postgresql://example:secret@example.invalid/test',
                'SECRET_KEY': 'a' * 48, 'JWT_SECRET_KEY': 'b' * 48}
        for values in ({}, {**base, 'JWT_SECRET_KEY': ''}, {**base, 'JWT_SECRET_KEY': 'short'},
                       {**base, 'SECRET_KEY': 'GENERAR_CLAVE_ALEATORIA'},
                       {**base, 'JWT_SECRET_KEY': base['SECRET_KEY']}):
            with self.subTest(values=list(values)), patch.dict('os.environ', values, clear=True):
                with self.assertRaises(RuntimeError):
                    get_config('production')
        with patch.dict('os.environ', base, clear=True):
            config = get_config('production')
        self.assertFalse(config.DEBUG)

    def test_server_port_host_and_service_timeout_are_configurable_and_validated(self):
        with patch.dict('os.environ', {'PORT': '5100', 'HOST': '127.0.0.2', 'MAP_SERVICE_TIMEOUT': '20'}, clear=True):
            config = get_config('testing')
        self.assertEqual((config.PORT, config.HOST, config.MAP_SERVICE_TIMEOUT), (5100, '127.0.0.2', 20))
        for key, value in [('PORT', '0'), ('PORT', '65536'), ('PORT', 'abc'), ('MAP_SERVICE_TIMEOUT', '-1')]:
            with self.subTest(key=key, value=value), patch.dict('os.environ', {key: value}, clear=True):
                with self.assertRaises(RuntimeError):
                    get_config('testing')

    def test_cors_accepts_only_explicit_origins(self):
        for origin in ('*', 'https://*.example.com', 'https://example.com/path', 'file:///private',
                       'https://example.com?key=value', 'https://user:password@example.com', 'http://[invalid'):
            with patch.dict('os.environ', {'CORS_ORIGINS': origin}, clear=True):
                with self.assertRaises(RuntimeError):
                    get_config('testing')
        with patch.dict('os.environ', {'CORS_ORIGINS': 'http://localhost:4200,https://example.com'}, clear=True):
            self.assertEqual(len(get_config('testing').CORS_ORIGINS), 2)

    def test_api_security_headers_and_request_size_limit(self):
        from app import create_app, db
        app = create_app('testing')
        try:
            response = app.test_client().get('/api/alerts/')
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
            response = app.test_client().post('/api/auth/login', data='x' * (app.config['MAX_CONTENT_LENGTH'] + 1),
                                               content_type='application/json')
            self.assertEqual(response.status_code, 413)
        finally:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()


if __name__ == "__main__":
    unittest.main()
