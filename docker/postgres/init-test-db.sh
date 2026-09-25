#!/bin/sh
# Выполняется один раз при первой инициализации тома pgdata.
# Создаёт отдельную БД для тестов: conftest.py делает drop_all/create_all по
# метаданным, поэтому TEST_DATABASE_URL нельзя направлять на рабочую БД
# POSTGRES_DB — тесты снесут её схему.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    SELECT 'CREATE DATABASE ${POSTGRES_TEST_DB}'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${POSTGRES_TEST_DB}')\gexec
EOSQL