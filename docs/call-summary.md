# Per-call summary (migration 044)

Each call stores its own `summary`, `urgency`, `key_details` and
`suggested_next_step`, written once when the end-of-call webhook is processed. The
calls page, call detail and rating breakdown read only these. The lead keeps its own
copy, which follows the newest call that was actually analysed; a call too short to
analyse no longer blanks it.

Calls processed before the release keep empty columns and show "No summary saved
for this call" and "Unrated". They are not backfilled: that would rewrite history,
and the analysis shown would not be the one made at the time.

## Release

The backend selects the new columns, so the migration goes first.

1. In the SQL Editor of project `gsylobklnpytitaqcley`, as `postgres`, confirm the
   columns don't exist yet:
   `select column_name from information_schema.columns where table_schema = 'public' and table_name = 'calls' and column_name in ('summary', 'urgency', 'key_details', 'suggested_next_step');`
   It should return no rows. If some exist, stop and compare their types with the
   migration first.
2. Apply `migrations/044_call_summary.sql`. It only adds nullable columns.
3. Re-run the query in step 1: four rows. Check that existing calls are untouched:
   `select count(*) filter (where summary is not null) from public.calls;` returns 0.
4. Check that browser roles still can't read calls (043):
   `select has_table_privilege('anon', 'public.calls', 'SELECT');` returns false.
5. Merge and deploy. Wait for `/health` to report the merge commit and for the
   previous deployment to show Removed.
6. Open the calls page: existing calls show "No summary saved for this call". After
   the next real call, its row shows its own summary and rating, and older calls
   from the same caller don't change.

## Rollback

Revert the backend and frontend. The columns can stay; nothing else reads them. To
remove them: `alter table public.calls drop column summary, drop column urgency, drop column key_details, drop column suggested_next_step;`
That deletes the summaries saved since the release.
