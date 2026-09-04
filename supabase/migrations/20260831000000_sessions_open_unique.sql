-- Migration: 20260831000000_sessions_open_unique.sql
-- Story 4-11 — Session dedup guard (calibration prerequisite)
--
-- Context
-- -------
-- React StrictMode double-renders useEffect in development, causing two concurrent
-- POST /api/assessment/sessions calls. Without this constraint, both inserts succeed
-- and quiz data fragments across two session IDs (confirmed: 4 duplicate pairs in
-- 2026-08-12 data, all at identical millisecond timestamps).
--
-- This is a PARTIAL index on `ended_at IS NULL` only.
-- It does NOT prevent re-taking a lesson after completion — rows with ended_at IS NOT
-- NULL are excluded, so a student who finishes lesson A and starts it again still gets
-- a fresh session row. The invariant "sessions are attempt-scoped" is preserved.
--
-- Application-level complement
-- ----------------------------
-- create_session() in assessment/service.py now queries for an existing open session
-- before inserting. This index is the concurrent-safe backstop: if two requests both
-- pass the application check simultaneously and race to insert, the second insert
-- fails; create_session's race-fallback then fetches and returns the winning row.
--
-- Apply before running the 20-session calibration run (Story 4-11, 2026-08-31).
-- See docs/sprint4-ces-calibration-notes.md §8 Item 4.
--
-- IMPORTANT: Run this in the Supabase SQL editor — do not run via apply_migration
-- without user confirmation (feedback_db_manipulation memory).

CREATE UNIQUE INDEX IF NOT EXISTS sessions_open_unique
    ON public.sessions (user_id, lesson_id)
    WHERE ended_at IS NULL;
