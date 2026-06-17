# Migration runbook

Operational notes for applying migrations to a **production Postgres** that the
`booking-agent` and `booking-mcp` services **share**. booking-agent owns the
schema; booking-mcp reads/writes the same tables, so a column's type must stay
compatible with *both* deployed code versions throughout a rollout.

General deploy order for any migration: **migrate first, then roll the code** —
each migration is written to be compatible with the previously-deployed code
(additive), so `alembic upgrade head` runs cleanly before the new app image goes
live.

---

## `f3a7c1d9e2b4` — `start_date` → `timestamptz` + tz-aware timestamps

This revision changes `appointments.start_date` from `VARCHAR(32)` to a real
timestamp and makes the instant columns (`created_at`/`updated_at`/`decided_at`)
timezone-aware.

### Why it needs care at scale

On Postgres, `ALTER COLUMN ... TYPE` with a `USING` cast **rewrites the whole
table** under an `ACCESS EXCLUSIVE` lock and rebuilds its indexes. That is:

- **Fine** for a fresh/empty DB or a small `appointments` table (sub-second) —
  the in-repo migration applies it directly, which is correct for the demo and
  for new deployments.
- **A downtime risk** on a large, live `appointments` table: the exclusive lock
  blocks all reads and writes for the duration of the rewrite.

(On SQLite — dev only — the migration is a guarded no-op that just normalises
legacy second-precision strings; see the migration docstring. None of the below
applies there.)

### Zero-downtime path for a large live table (expand → backfill → contract)

Run this **instead of** the direct `alembic upgrade head` when `appointments` is
large. It replaces the one in-place `ALTER` with online steps:

1. **Expand** — add the new column nullable (instant in PG ≥ 11; no rewrite):
   ```sql
   ALTER TABLE appointments ADD COLUMN start_date_ts timestamptz;  -- nullable, no default
   ```
2. **Dual-write** — deploy app code (or a trigger) that writes **both**
   `start_date` and `start_date_ts` on every insert/update, so new rows stay in
   sync while the backfill runs:
   ```sql
   CREATE FUNCTION appt_sync_start_ts() RETURNS trigger AS $$
   BEGIN NEW.start_date_ts := NEW.start_date::timestamptz; RETURN NEW; END;
   $$ LANGUAGE plpgsql;
   CREATE TRIGGER appt_sync_start_ts BEFORE INSERT OR UPDATE ON appointments
     FOR EACH ROW EXECUTE FUNCTION appt_sync_start_ts();
   ```
3. **Backfill in batches** — avoid one long transaction / table-wide lock & bloat:
   ```sql
   -- repeat until 0 rows; chunk by PK, brief pause between batches
   UPDATE appointments SET start_date_ts = start_date::timestamptz
   WHERE start_date_ts IS NULL AND id IN (
     SELECT id FROM appointments WHERE start_date_ts IS NULL LIMIT 5000
   );
   ```
4. **Build indexes without locking** — mirror the existing ones on the new column:
   ```sql
   CREATE INDEX CONCURRENTLY ix_appointments_start_date_ts ON appointments (start_date_ts);
   CREATE INDEX CONCURRENTLY ix_appt_staff_start_ts ON appointments (staff_id, start_date_ts);
   ```
5. **Verify** — `SELECT count(*) FROM appointments WHERE start_date_ts IS NULL;`
   must be `0`, and a spot-check that values match.
6. **Contract / swap** — in one short transaction (brief lock only), drop the
   trigger + old column and rename:
   ```sql
   DROP TRIGGER appt_sync_start_ts ON appointments;
   ALTER TABLE appointments DROP COLUMN start_date;
   ALTER TABLE appointments RENAME COLUMN start_date_ts TO start_date;
   ALTER INDEX ix_appointments_start_date_ts RENAME TO ix_appointments_start_date;
   ALTER INDEX ix_appt_staff_start_ts RENAME TO ix_appt_staff_start;
   ```
   Then `alembic stamp f3a7c1d9e2b4` so Alembic's history matches without
   re-running the in-place ALTER.

The `created_at`/`updated_at`/`decided_at` columns are write-light; convert them
the same way if their tables are large, or accept a brief low-traffic window.

### Rollback

Until step 6, the original `start_date` column is intact and the app can be
rolled back with no data loss. After the swap, roll back by reversing the rename
(the data is unchanged — only the declared type differs). Always snapshot/backup
before the contract step.

### Tooling alternative

For very large tables, `pg_repack` or a managed online-DDL tool can perform the
type change without holding a long exclusive lock — equivalent to the manual
expand/backfill/contract above.
