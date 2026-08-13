-- D74: Replace Python-side session_count read-modify-write with a server-side
-- atomic UPDATE so concurrent fuse_learner_dna calls for the same user_id
-- cannot silently drop a session's contribution.
--
-- Before: Python reads old_session_count, adds 1, writes it back in the upsert
--         payload.  Two concurrent calls both read N, both write N+1 →
--         session_count = N+1 instead of N+2.
-- After:  The upsert payload carries only the 9 EMA dimensions.  This function
--         is called once per completed session to atomically increment the counter.

create or replace function public.increment_learner_dna_session_count(p_user_id uuid)
returns void
language plpgsql
security invoker
set search_path = ''
as $$
begin
    update public.learner_dna
    set session_count = session_count + 1
    where user_id = p_user_id;
end;
$$;

revoke execute on function public.increment_learner_dna_session_count(uuid) from public;
revoke execute on function public.increment_learner_dna_session_count(uuid) from anon;
revoke execute on function public.increment_learner_dna_session_count(uuid) from authenticated;
grant  execute on function public.increment_learner_dna_session_count(uuid) to service_role;
