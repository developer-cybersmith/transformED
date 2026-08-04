/**
 * The frozen book-scale API contract, loaded as data — not re-typed by hand.
 *
 * `docs/contracts/book-api.v1.json` is the single source of truth for every
 * fixture in this directory (Story W0 AC2). Importing the JSON rather than
 * copying values out of it is deliberate: a hand-copied fixture drifts from the
 * contract silently, which is exactly the class of failure this harness exists
 * to make loud.
 *
 * Do NOT confuse this with `apps/web/src/mocks/`. That is a hand-rolled layer of
 * plain async functions imported directly by services — it never touches the
 * network and cannot disagree with an HTTP contract. This directory intercepts
 * real HTTP.
 */
import contractJson from '../../../../docs/contracts/book-api.v1.json';

export const contract = contractJson;

/** Keys that document the schema rather than naming a response field. */
const NON_FIELD_KEYS = new Set(['$comment', 'added_in']);

function schemaFieldNames(schemaName: string): string[] {
    const schemas = contract.schemas as unknown as Record<string, Record<string, unknown>>;
    const schema = schemas[schemaName];
    if (!schema) {
        throw new Error(
            `book-api.v1.json has no schema named "${schemaName}" — the contract moved under the harness.`
        );
    }
    return Object.keys(schema).filter((k) => !NON_FIELD_KEYS.has(k));
}

/**
 * Provenance guard.
 *
 * `real_example` and `schemas` are two independently maintained blocks of the
 * same JSON file. Asserting that a captured payload carries exactly the field
 * names its schema declares is therefore a real comparison, not a tautology:
 * renaming a field in either block alone fails here, at import time, before a
 * single test body runs.
 *
 * This is the mechanism AC4's mutation check exercises.
 */
export function assertExampleMatchesSchema(schemaName: string, example: unknown, where: string): void {
    const expected = schemaFieldNames(schemaName).sort();
    const actual = Object.keys(example as Record<string, unknown>).sort();

    const missing = expected.filter((k) => !actual.includes(k));
    const extra = actual.filter((k) => !expected.includes(k));

    if (missing.length > 0 || extra.length > 0) {
        throw new Error(
            `book-api.v1.json ${where} does not match schema ${schemaName}. ` +
            `Missing field(s): [${missing.join(', ')}]. Unexpected field(s): [${extra.join(', ')}]. ` +
            `real_example and schemas are the same frozen contract — one of them was changed alone.`
        );
    }
}

/** Contract constant: the chapter page-span ceiling that produces `chapter_too_large`. */
export const MAX_PAGE_SPAN = 200;

/**
 * Contract constant: above this span the LLM-visible window covers only part of
 * the chapter, so `truncation_expected` is true. See LessonGenerationResponse.
 */
export const TRUNCATION_WARN_PAGES = 40;
