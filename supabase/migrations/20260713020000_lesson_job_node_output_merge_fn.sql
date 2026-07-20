-- Atomic per-section checkpoint merge for Phase 1 economy nodes (Story 2-1b).
--
-- Phase 1 economy nodes (summarise_segment, quiz_generator, segment_complexity,
-- jargon_extractor, intervention_messages, narration_generator) are dispatched
-- via LangGraph Send(), once per section -- up to 6 x N concurrent calls
-- sharing ONE lesson_jobs row. The existing Phase A checkpoint pattern
-- (extract/structure/chunk/embed) does a client-side read-modify-write of the
-- whole node_outputs JSONB blob, which is safe there because those nodes run
-- strictly sequentially (one at a time) -- it is NOT safe for concurrent
-- Phase 1 dispatches: two concurrent read-modify-write cycles on the same row
-- can silently lose one write (classic lost-update race).
--
-- This function performs the merge server-side in a single atomic UPDATE, so
-- concurrent callers each merge against the row's current state at the
-- instant of their own UPDATE, with no client-side read step to go stale.
--
-- Security review findings applied (Story 2-1b code review, 2026-07-13):
--   - `security invoker` (default, explicit here) + `set search_path = ''` +
--     schema-qualified `public.lesson_jobs`: prevents a same-named shadow
--     object earlier in a caller's search_path from silently hijacking the
--     write.
--   - REVOKE + explicit GRANT: Postgres grants EXECUTE on new functions to
--     PUBLIC by default, and Supabase/PostgREST auto-exposes every
--     public-schema function as a `/rest/v1/rpc/` endpoint. Only the
--     server-side ARQ worker (using the service_role key) calls this
--     function -- `anon`/`authenticated` must never be able to reach it,
--     since it bypasses lesson_jobs' RLS entirely (it's an UPDATE run with
--     the function's own privileges, not a per-row-policy-checked one).
--   - `if not found then raise exception`: the previous version was a bare
--     `language sql` UPDATE, which returns success with 0 rows affected if
--     `p_lesson_id` matches no row -- silently losing the checkpoint (LLM
--     call billed, but nothing recorded, so a retry re-bills it). PL/pgSQL
--     is required to inspect FOUND after the UPDATE.
create or replace function merge_lesson_job_node_output(
    p_lesson_id uuid,
    p_key text,
    p_value jsonb
) returns void
language plpgsql
security invoker
set search_path = ''
as $$
begin
    update public.lesson_jobs
    set node_outputs = coalesce(node_outputs, '{}'::jsonb) || jsonb_build_object(p_key, p_value)
    where lesson_id = p_lesson_id;

    if not found then
        raise exception 'merge_lesson_job_node_output: no lesson_jobs row for lesson_id %', p_lesson_id;
    end if;
end;
$$;

revoke execute on function merge_lesson_job_node_output(uuid, text, jsonb) from public;
revoke execute on function merge_lesson_job_node_output(uuid, text, jsonb) from anon;
revoke execute on function merge_lesson_job_node_output(uuid, text, jsonb) from authenticated;
grant execute on function merge_lesson_job_node_output(uuid, text, jsonb) to service_role;
