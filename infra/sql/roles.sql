-- One-time: the homecloud database and the role the API connects as, on the shared Postgres
-- (postgres.ad.gavinf.com). Run it once as a superuser. The API creates its own two tables
-- on startup (backend/app/db.py), so the role owns the database.
--
-- The password is a psql variable, so it never lands in this file:
--
--   PW=$(openssl rand -hex 24)
--   docker run --rm -i postgres:18.4 psql "postgresql://postgres:<superuser pw>@postgres.ad.gavinf.com:5432/postgres" \
--     -v ON_ERROR_STOP=1 -v password="$PW" < infra/sql/roles.sql
--   echo "postgresql://homecloud:$PW@postgres.ad.gavinf.com:5432/homecloud"   # -> Infisical, HOMECLOUD_DATABASE_URL
--
-- Safe to re-run: only creates what's missing, and never changes an existing password.

select format('create role homecloud login password %L', :'password')
where not exists (select from pg_roles where rolname = 'homecloud')
\gexec

select 'create database homecloud owner homecloud'
where not exists (select from pg_database where datname = 'homecloud')
\gexec

\connect homecloud
revoke all on database homecloud from public;
alter schema public owner to homecloud;
revoke create on schema public from public;
