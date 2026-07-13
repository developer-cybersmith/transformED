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
create or replace function merge_lesson_job_node_output(
    p_lesson_id uuid,
    p_key text,
    p_value jsonb
) returns void
language sql
as $$
    update lesson_jobs
    set node_outputs = coalesce(node_outputs, '{}'::jsonb) || jsonb_build_object(p_key, p_value)
    where lesson_id = p_lesson_id;
$$;
