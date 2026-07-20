-- Story 3-18: Add UNIQUE constraint on onboarding_responses(user_id, question_id)
-- Prevents duplicate question answers per user; enables safe ON CONFLICT DO UPDATE upsert
-- pattern if needed in future. Also provides the idempotency check at DB layer in addition
-- to the Redis onboarding_done flag already enforced in the router.

ALTER TABLE onboarding_responses
    ADD CONSTRAINT onboarding_responses_user_question_unique
    UNIQUE (user_id, question_id);
