# New Task Specifications (Phase 1 of Option-2 Plan)

7 new tasks designed to fill the thin categories C (Multi-condition filter)
and D (Cross-app correlation) in the CLI-advantage benchmark, lifting both
to ≥8 tasks for true soft balance (8–12 per category).

**Status: APPROVED. Moving to Phase 2 (implementation).**

## Cross-cutting design decisions

1. **Tolerant evaluation**: each task accepts multiple equivalent forms for
   empty results (`None`, `none`, `""`, etc.) and normalizes whitespace,
   case (where appropriate), phone-number / email format.
2. **Seed-varying placeholders**: every task has at least one parameter
   that changes across seeds, so the same task ID produces a different
   concrete query at seed=7 vs seed=30 vs seed=1234. The agent always sees
   substituted values — no `{placeholder}` literals.
3. **User-level goal text**: no implementation details (file paths, DB
   names, file extensions). The agent figures out which app/data source to
   query.

## Per-seed placeholder values

| Task | Placeholder | seed=7 | seed=30 | seed=1234 |
|---|---|---|---|---|
| C1 | `{N}` days | 7 | 14 | 30 |
| C2 | `{K}` days | 7 | 14 | 30 |
| C3 | `{M}` months | 1 | 3 | 12 |
| D1 | `{K}` days | 7 | 14 | 30 |
| D2 | `{M}` months | 3 | 6 | 12 |
| D3 | `{artist}` | `Aria Voss` | `Marcus Reed` | `The Stillwaters` |
| D4 | `{M}` months | 1 | 3 | 6 |

---

## C1. Unread SMS not replied to in last {N} days

| Field | Spec |
|---|---|
| User intent | "Who texted me recently that I never got back to?" |
| Goal text | List phone numbers that have sent you SMS in the last {N} days where (a) you have at least one unread message from them, AND (b) you have not sent any SMS to them in the same {N} days. Output one number per line. If none, output 'None'. |
| Initial state | ~12 inbox SMS spread over ~45 days from 5–7 distinct numbers. ~3 numbers satisfy (unread + no recent reply within N) = answer. ~2 numbers are unread but DO have a recent reply = excluded. Rest are read or older than N. |
| Eval | Set equality on normalized phone numbers (strip `+`, dashes, parens, spaces). |
| Tolerance | Empty: `"None"`, `"no one"`, `"0"`, `""`. Phone format: any. |
| Implementation domain | `tier4/sms.py` |

## C2. Overlapping calendar events in next {K} days

| Field | Spec |
|---|---|
| User intent | "Where do I have schedule conflicts I should fix?" |
| Goal text | Find all pairs of calendar events starting within the next {K} days that overlap in time (one starts before the other ends). Output each pair as 'EventA / EventB', one pair per line. If no overlaps, output 'No overlaps'. |
| Initial state | ~10 events across next K days. 2–3 deliberate overlap pairs (titles distinct), rest non-overlapping distractors. |
| Eval | Unordered pair-set equality. Each output line split by ` / ` → frozenset({A, B}). |
| Tolerance | Pair order ignored. Empty: `"No overlaps"`, `"none"`, `""`. |
| Implementation domain | `tier4/calendar.py` |

## C3. Contacts with no email AND no calls in last {M} months

| Field | Spec |
|---|---|
| User intent | "Clean up my contacts — find people I'm not in touch with at all." |
| Goal text | List all contacts that have no email address AND no calls (incoming or outgoing) in the last {M} months. Output the contact names, one per line. If none, output 'None'. |
| Initial state | ~12 contacts. ~6 have email, ~6 don't. Call log populated such that ~3–4 of the no-email contacts have no calls in the last M months — these are the answer. |
| Eval | Set equality on lowercased trimmed names. |
| Tolerance | Case-insensitive. Whitespace-tolerant. Empty: `"None"`, `"none"`, `""`. |
| Implementation domain | `tier4/contacts.py` |

## D1. Calendar attendees not in my contacts (next {K} days)

| Field | Spec |
|---|---|
| User intent | "Who's invited to my upcoming meetings that I don't have saved?" |
| Goal text | List all distinct attendee email addresses of calendar events starting in the next {K} days who are NOT in your contacts (matched by their email). Output one email per line. If all attendees are known contacts, output 'all known'. |
| Initial state | ~5 events with attendees field. 4–6 distinct attendee emails overall. ~2 emails ARE in contacts (excluded). ~2–3 emails are NOT (the answer). |
| Eval | Set difference: event.attendees − contacts.emails. Email lowercased + trimmed. |
| Tolerance | Accept `<x@y.com>`, `x@y.com`, `x@y.com (Name)`. Case-insensitive. Empty: `"all known"`, `"none"`, `""`. |
| Implementation domain | `tier4/cross_app.py` |

## D2. Texted but never called in last {M} months

| Field | Spec |
|---|---|
| User intent | "Who do I only text? Maybe I should call them sometime." |
| Goal text | List names of contacts to whom you have sent at least one SMS in the last {M} months but with whom you have NO phone calls (incoming or outgoing) in the same {M} months. Match by phone number. Output one name per line. If none, output 'None'. |
| Initial state | ~10 contacts. Sent SMS log has ~5 contacts texted in last M months. Call log has ~3 of those contacts in same window. Answer: contacts in (texted ∖ called) within window. ~2–3 expected. |
| Eval | Set equality on contact names. |
| Tolerance | Case-insensitive. Empty: `"None"`, `"none"`, `""`. |
| Implementation domain | `tier4/cross_app.py` |

## D3. Songs from my music library mentioned in my notes (by artist '{artist}')

| Field | Spec |
|---|---|
| User intent | "I write about specific artists' songs in my notes — find them." |
| Goal text | I sometimes write song names in my notes (Markor app). List the songs by artist '{artist}' in my music library (Retro Music app) whose titles appear anywhere in any of my Markor notes (case-insensitive substring match). Output one song title per line. If none, output 'None'. |
| Initial state | ~12 songs in Retro Music DB across 3–4 artists; chosen `{artist}` has 4 songs. Markor has ~5 notes; 2–3 mention the artist's songs by exact title (mixed case). Other songs and artists serve as distractors. |
| Eval | For each song-by-{artist}, check whether `title.lower()` appears in any note's lowercased text. Set equality on matched song titles. |
| Tolerance | Case-insensitive substring match. Empty: `"None"`, `"none"`, `""`. |
| Implementation domain | `tier4/cross_app.py` |

## D4. Pro Expense entries on days with no calendar events (last {M} months)

| Field | Spec |
|---|---|
| User intent | "What did I spend money on during quiet days?" |
| Goal text | List all Pro Expense entries (by name) whose date matches a day in the last {M} months that had ZERO calendar events. Output one expense name per line. If every expense was on a day with at least one event, output 'all on event days'. |
| Initial state | Calendar events on ~10 days within the last M months. ~15 expenses across the window — ~5 of them on no-event days. Expected: ~5 expense names. |
| Eval | Set equality on expense names (case-insensitive). |
| Tolerance | Case-insensitive. Empty: `"all on event days"`, `"none"`, `""`. |
| Implementation domain | `tier4/cross_app.py` |

---

## Implementation order (Phase 2)

Easiest → hardest, so we de-risk early failures:

1. **D1** — simple set-difference, similar to existing task 4
2. **D2** — analogous to D1 with one extra table
3. **C2** — temporal self-join, single-table
4. **C1** — multi-condition with sent-SMS lookup
5. **C3** — multi-table NULL + temporal
6. **D4** — date arithmetic + cross-app
7. **D3** — text search across files + DB join (most complex)

After each, run a unit test before moving on.

## Expected task IDs after registration

The current registry has 77 tasks (IDs 0–76). The 7 new tasks will get IDs
77–83 in registration order. Each will be appended to the relevant module's
class list and to the `_TIER4_TASKS` tuple in `registry_ext.py`.

## Final balanced subset after these 7 land

| Cat | Before | + new | After |
|---|---:|---:|---:|
| A | 12 | — | 12 |
| B | 8 | — | 8 |
| C | 6 | +3 (C1, C2, C3) | **9** |
| D | 6 | +4 (D1, D2, D3, D4) | **10** |
| E | 6 | — | 6 |
| **Total** | 38 | +7 | **45** |

C and D both clear the 8-task floor. Soft balance achieved.
