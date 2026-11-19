"""Pruebas sobre una BD PostgreSQL dedicada; nunca apuntar a la BD de trabajo."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
import psycopg2
from psycopg2.extensions import adapt, parse_dsn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

class SingleDatabaseError(psycopg2.DatabaseError):
    @property
    def pgcode(self):
        return self.code
    @property
    def diag(self):
        return SimpleNamespace(message_primary=self.message)

@pytest.fixture(scope='session')
def app():
    # La variable de pruebas siempre es explícita. El modo --single sirve en entornos sin sockets.
    url = os.environ.get('J2F_TEST_DATABASE_URL')
    pgdata = os.environ.get('J2F_TEST_SINGLE_DATA')
    if not url and not pgdata:
        pytest.skip('Configura J2F_TEST_DATABASE_URL con una base dedicada cuyo nombre termine en _test')
    import app.database as database
    original_invoke = database.invoke
    directory = Path(__file__).resolve().parents[2] / 'database'
    if pgdata:
        import pgserver
        binary = Path(pgserver.__file__).parent / 'pginstall/bin/postgres'
        assert Path(pgdata).name.endswith('_test'), 'La carpeta de pruebas debe terminar en _test'
        def execute(sql):
            sql = '\n'.join(line for line in sql.splitlines() if line.strip())
            result = subprocess.run([str(binary), '--single', '-j', '-D', pgdata, '-c', 'log_error_verbosity=verbose', 'postgres'], input=sql, text=True, capture_output=True)
            error = re.search(r'ERROR:\s+([A-Z0-9]{5}):\s+(.*)', result.stderr)
            if error:
                failure = SingleDatabaseError(error[2]); failure.code=error[1]; failure.message=error[2]
                raise failure
            assert result.returncode == 0, result.stderr
            return result.stdout
        def invoke(name, *parameters):
            def quote(value):
                if value is None:
                    return 'NULL'
                if isinstance(value,(dict,list)):
                    return "'"+json.dumps(value,ensure_ascii=True).replace("'", "''")+"'::jsonb"
                if isinstance(value,(int,float)):
                    return str(value)
                return "'"+str(value).replace("'", "''")+"'"
            output=execute('SELECT '+name+'('+','.join(quote(p) for p in parameters)+')::text;')
            match=re.search(r' = "(.*)"\s*\(typeid',output)
            return database.utc_json(json.loads(match[1])) if match else None
        database.invoke=invoke
        execute('DROP SCHEMA public CASCADE; CREATE SCHEMA public;')
        for name in ('01_esquema.sql','02_catalogos.sql','03_funciones.sql'):
            execute((directory/name).read_text(encoding='utf-8'))
        os.environ['DATABASE_URL']='postgresql://localhost/j2f_test'
    else:
        assert parse_dsn(url).get('dbname','').endswith('_test'), 'Se rechaza una base no identificada como _test'
        with psycopg2.connect(url) as connection:
            with connection.cursor() as cursor:
                cursor.execute('DROP SCHEMA public CASCADE; CREATE SCHEMA public;')
                for name in ('01_esquema.sql','02_catalogos.sql','03_funciones.sql'):
                    cursor.execute((directory/name).read_text(encoding='utf-8'))
        os.environ['DATABASE_URL']=url
    from app import create_app
    application=create_app()
    application.config['TESTING']=True
    if pgdata:
        application.config['TEST_SQL'] = execute
    else:
        def execute_script(sql):
            with psycopg2.connect(url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(sql)
        application.config['TEST_SQL'] = execute_script
    with application.app_context():
        from werkzeug.security import generate_password_hash
        database.invoke('j2f_bootstrap','12345678','Administrador de pruebas','admin@test.local',generate_password_hash('PruebaClave123'))
    yield application
    database.invoke=original_invoke

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def admin(client):
    response=client.post('/api/auth/login',json={'identifier':'admin@test.local','password':'PruebaClave123'})
    assert response.status_code==200, response.json
    return {'Authorization':'Bearer '+response.json['access_token']}
