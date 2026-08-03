-- ============================================================
-- Supabase shim for real-Postgres migration replay (TEST ONLY)
--
-- Story 1-9 / book-scale Phase 2. NOT a migration — this file lives under
-- tests/ and is never applied to a real environment.
--
-- WHY THIS EXISTS
-- The migration chain in supabase/migrations/ depends on three objects that
-- Supabase provisions and that a stock Postgres image does not have:
--
--   auth.users        FK target  (20260611000000_initial_schema.sql:69)
--                     trigger source (:75-77)
--   auth.uid()        66 references across the chain, every RLS policy
--   storage.buckets   insert target (20260710000000_storage_buckets.sql:18)
--
-- Without these, `psql -f 20260611000000_initial_schema.sql` fails on line 69
-- and nothing downstream can be verified at all.
--
-- FIDELITY — READ BEFORE TRUSTING A RESULT FROM THIS FILE
-- This shim reproduces the *contract* these objects expose to our migrations,
-- not Supabase's implementation. Specifically:
--   - auth.uid() here reads the same GUC Supabase uses,
--     `request.jwt.claims` -> 'sub', so `SET LOCAL request.jwt.claims` is a
--     faithful way to act as a given user.
--   - It returns NULL when the GUC is unset or malformed, matching Supabase.
--   - It is NOT SECURITY DEFINER and grants nothing; RLS behaviour under test
--     comes from the policies in the migrations, not from here.
--
-- This shim is an executable premise (binding rule 3): if Supabase ever changes
-- the claim path, `test_shim_auth_uid_reads_jwt_claims` fails loudly rather
-- than silently validating the wrong thing.
-- ============================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

-- ── auth ────────────────────────────────────────────────────
CREATE SCHEMA IF NOT EXISTS auth;

CREATE TABLE IF NOT EXISTS auth.users (
  id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email text
);

-- Mirrors supabase's auth.uid(): the current request's JWT `sub` claim.
CREATE OR REPLACE FUNCTION auth.uid()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
  SELECT NULLIF(
    current_setting('request.jwt.claims', true)::jsonb ->> 'sub',
    ''
  )::uuid;
$$;

-- ── storage ─────────────────────────────────────────────────
CREATE SCHEMA IF NOT EXISTS storage;

CREATE TABLE IF NOT EXISTS storage.buckets (
  id     text PRIMARY KEY,
  name   text NOT NULL,
  public boolean NOT NULL DEFAULT false
);

-- ── test roles ──────────────────────────────────────────────
-- `app_user` is RLS-bound and stands in for an end user's PostgREST
-- connection. The owner/superuser running the replay stands in for the
-- service-role key, which bypasses RLS — the contrast AC16 requires.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
    CREATE ROLE app_user NOLOGIN;
  END IF;
END
$$;

GRANT USAGE ON SCHEMA public, auth, storage TO app_user;
