# /add-migration

Create a new Supabase database migration.

## Usage
`/add-migration <description>`

Example: `/add-migration add-stripe-customer-id-to-users`

## What it creates

File: `supabase/migrations/<timestamp>_<description>.sql`

Where `<timestamp>` = current UTC datetime in format `YYYYMMDDHHMMSS`.

## Rules (CRITICAL — from PRD §16)
- **NEVER modify an already-applied migration** — always create a new file
- RLS policies must be included for any new table
- Add indexes for all new foreign key columns
- Follow the existing naming convention: snake_case table and column names
- If adding a column to an existing table: use `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
- If dropping a column: create a compensating migration, do not edit the original
- Test the migration locally with `supabase db reset` before committing

## Migration file template
```sql
-- Migration: <description>
-- Created: <date>
-- Author: <name>

-- ============ CHANGES ============

ALTER TABLE public.<table>
  ADD COLUMN IF NOT EXISTS <column> <type> <constraints>;

-- ============ INDEXES ============

CREATE INDEX IF NOT EXISTS idx_<table>_<column>
  ON public.<table> (<column>);

-- ============ RLS ============
-- Add new policies if needed
```
