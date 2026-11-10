# Household access and managed child accounts

## Implemented access layers

1. **Account identity:** authentication, active account and adult/managed-child
   status. Managed-child status belongs to the account, not a household.
2. **Household membership:** the selected membership determines the household,
   owner/member role and local access choices. `family_id` remains the hard
   boundary between households.
3. **Module access:** `HouseholdMembership.allowed_modules` grants `finance`
   and/or `household`. Household owners manage these under Central settings,
   **Household & people > Member access**, independently for each membership.
4. **Feature permissions:** Finance sections further restrict a granted module.
   Removing module access preserves section choices, so restoring the module
   restores only previously permitted sections.
5. **Record privacy:** existing shared/private record rules still apply. Owners,
   module grants and guardianship do not override private Finance records.

Module access is checked on requests, not just navigation. Registered module
routes, dashboards, APIs and downloads, plus Core financial export and legacy
financial administration endpoints, are guarded. Revocation takes effect on
the next request in existing sessions. Inaccessible saved starting points fall
back to Central Hub; explicit protected links are denied.

Owners can recover their own revoked module access through Central settings.
Core appearance and sign-in security remain available without Finance.
These grants are **not subscription or billing entitlements**. A future billing
layer must compose with membership and account restrictions, not replace them.

## Managed child accounts

An active household owner can create a **new** managed-child account through
**Settings > Household & people > Add child**, providing an account name, unique sign-in email and an
initial password meeting the normal password policy. The creating owner becomes
the designated guardian. Existing adult accounts cannot be converted or taken
over. Child creation does not bypass normal sign-in/email-verification controls.

Children start as members with Household Hub allowed, no Finance grant and no
Finance sections. Finance, household administration, self-joining households,
self-deletion and operator tools remain blocked across households even if a
local role or module grant is incorrect. Children can use the Household Hub
calendar, My day, appearance and sign-in security.

Children with Household Hub access start at `/household/my-day` after sign-in
and on `/`; `/central/` renders the same child page. Explicit safe destinations are
preserved and still enforce access. My day uses London's current date, shows
all approved household activities (not just those they attend), privacy-scoped
manual events, their own actionable tasks/jobs and reward progress. Pending
activity suggestions, siblings' work and private adult records stay hidden.
Earlier work is separate; approval and point-reservation rules are unchanged.
Revoking Hub access denies My day immediately. Detached accounts retain the
Account security fallback.

Owners have an optional read-only setup checklist at `/central/setup`. It links
the existing people, access, tasks and rewards editors and respects the selected
household and module grants. It neither creates sample records nor grants access.

Only the designated guardian can transfer guardianship or release the account
into an adult account, under Settings, **Children you supervise**.
A transfer target must be an active adult sharing one of the child's households.
Other household owners control only their own module grants, not child status.
Release preserves all module grants; it never enables Finance automatically.
Guardians must transfer or release dependent accounts before deleting their own
account.

Grant changes, child creation, guardian transfer and release require recent
authentication and CSRF protection. Audit events commit in the same transaction
as the changes; a failed write saves neither.

## Household calendar (implemented)

Household Hub opens at `/household/` with month and agenda views and manually
created all-day/timed events in `Europe/London`. Meal plans, approved activities
and visible incomplete dated tasks also contribute source-linked items.

- Shared and private events have explicit visibility. Adult-private events are
  creator-only; child-private events are visibly labelled as accessible to the
  child and designated guardian **within the same household**. Guardianship does
  not grant membership or bypass module access in another household.
- Edit and delete permissions are separate: creator-only, selected members or
  all household members. Owners retain management of shared events, never an
  override of someone else's private items.
- Selected-member permissions use membership IDs, not account IDs. Rejoining a
  household does not restore an old event grant: departure removes selected
  grants so reused database IDs cannot inherit them. Private events can grant edit
  or delete permission only to their creator or the child's designated guardian.
- Only the creator or an owner of a shared event changes its visibility and
  permission policies. Other editors change content only. Viewing a child-private
  event does not automatically grant the guardian edit/delete permission.
- A guardian transfer immediately removes the old guardian's private visibility;
  the new guardian still needs household membership and Household Hub access.
- When a creator leaves or deletes their account, private events are removed.
  Shared events remain with the household, detached from their former creator,
  and owners manage them. Existing other-member edit/delete grants remain.
- All-day end dates are inclusive. Timed event input/display is London-local,
  stored as UTC. Events ending exactly at midnight do not occupy the next day.
  Nonexistent spring clock-change times and ambiguous autumn times are rejected
  with an explicit instruction to choose an unambiguous time.

## Shared meal planning (implemented)

- The household meal library stores names, ingredients, instructions and recipe sources.
  Active adults with Household Hub access manage meals and plans, regardless of
  household role or Finance permissions. Managed children can view only, including
  when a corrupt household role says owner. These rules apply in services and routes.
- The date-first week/month planner supports per-day quick-add and multiple meals
  per breakfast, lunch or dinner slot. Each entry has its own title, description,
  recipe source and optional planning notes. Library selection is optional and
  copies details once. Plans use London calendar dates, not UTC timestamps, and
  submitted meal IDs must be in the selected household.
- Month and agenda calendars read plans directly, linking to their planner
  entries. No manual `CalendarEvent` is generated. Planned-detail changes, moves
  and removals are immediately reflected; calendar event permissions are not
  used to bypass meal permissions.
- Meals are archived rather than deleted. Existing plans remain visible and
  editable; archived meals cannot be added to new plans until restored.
  Updating a library meal never changes existing planned details. Editing one
  planned meal changes neither other dates nor the library.
- All meals and plans are shared household records. They survive individual
  membership/account deletion and are removed child-first on household deletion.
  Added-by attribution uses the active household membership; departing members'
  attribution is cleared so a reused membership ID cannot claim old plans.
  There is no private-meal mode, cross-household sharing or Finance integration.

## Household activities (implemented)

- Published activities are shared with the selected household. Adults with
  Household Hub access create, edit, delete and review activities, independent of
  household role or Finance permissions. Attendance is descriptive, not an ACL.
- Managed children can suggest activities and edit/resubmit or withdraw their own
  pending/rejected suggestions. They cannot publish, approve/reject, or edit/delete
  approved activities, including when a corrupt household role says owner.
- Pending/rejected suggestions are visible only to the creator and household
  adults with Hub access, including their attendees. They never enter the calendar.
  An adult must explicitly approve; editing a pending suggestion alone does not
  publish it. Child revisions clear previous review attribution and resubmit.
- Activities support all-day or timed multi-day spans, location, description,
  comments and optional active-household attendees. Submitted membership IDs are
  scoped to the selected household; creator/reviewer/status cannot be spoofed.
- Weekly repeats keep their Europe/London clock times through DST and require
  an inclusive last-start date. All occurrence times are validated on save;
  ambiguous/nonexistent wall times must be changed before publishing or suggesting.
  Edits and deletions affect the whole series, including past dates. Individual
  exceptions/cancellations are not implemented.
- Approved occurrences feed the month/agenda calendar directly. No manual
  calendar events or separate occurrence records are generated.
- Activity series and suggestions survive individual membership/account deletion.
  Attendance links are removed and creator/reviewer attribution cleared on departure,
  preventing reused membership IDs from inheriting attribution. Household deletion
  removes attendees before activities. No cross-household sharing is enabled.

## Tasks & lists (implemented)

- Every list/task is scoped to the selected household, including personal lists.
  Lists are either shared with household members who have Hub access or personal.
  Adult personal lists are creator-only with no household-owner override. A
  child's personal list is also visible to their designated guardian within the
  same household, but only the child manages it. Tasks inherit list visibility
  in scoped helpers, stats, details and calendar feeds.
- Adults manage shared lists/tasks regardless of household role or Finance
  access. Children cannot create/edit/delete shared lists or task details; they
  can only complete or reopen shared tasks assigned to their own membership.
  A corrupt owner role never overrides account-level child restrictions.
  Children can create/manage their own personal lists/tasks.
- Personal tasks can be assigned only to the list creator or left unassigned.
  Shared tasks can be assigned to an active member of the selected household.
  Assignment grants no visibility or additional permissions.
- List privacy is immutable after creation; tasks cannot move between lists.
  This intentionally differs from the original hub's mutable privacy to prevent
  accidentally publishing private work. List deletion removes its tasks.
- Completion is an explicit POST complete/reopen action, not an unsafe toggle.
  Creator/completer and completion time are server-controlled. Repeating a
  completion preserves its actor/time; reopening clears them. Ordinary tasks
  have no approval step. Reward-bearing tasks submit separately for points approval.
- Optional due dates are London calendar dates; due times require dates and
  reject ambiguous/nonexistent DST times. Incomplete dated tasks appear directly
  in each authorised viewer's month/agenda calendar, not duplicate manual events.
  Completed tasks remain in the hub's completed/all filters; reopening restores
  calendar visibility. Today/overdue filters are date-based, not time-based.
- Membership/account departure deletes personal lists/tasks, retains shared
  work and clears creator/assignee/completer links. Completion timestamps remain.
  This prevents reused membership IDs inheriting assignments or attribution.
  Household deletion removes tasks before lists and memberships.

## Rewards (implemented)

- Rewards belongs to Household Hub, never Finance. Any active adult with Hub
  access can set up shared-task jobs/rewards, review a child's finished work and
  approve/decline reward requests. This does not require household ownership or
  designated guardianship. Child status is account-level, not a mutable role.
- Children have My jobs, My rewards and My progress screens with labelled,
  large controls. They see only their own reward jobs, goals, balances, requests
  and point history through scoped helpers; no sibling/guardian visibility
  override applies to reward progress. The catalogue is household-shared.
- Rewards opens on a reward-focused Overview for adults and children. Personal
  milestones use lifetime approved-job awards (first job, 5 jobs, 10 jobs and
  100 earned points); spending and pending reservations do not remove achievements.
  Milestones are calculated from the ledger, not separate awards or bonus points.
- The weekly leaderboard is off by default. Any adult with Household Hub
  access can enable or disable it for the selected household in Setup & approvals.
  When enabled, children see active household children's names, weekly earned
  point totals, weekly approved-job counts, ranks and lifetime milestones only.
  Weeks run Monday-Sunday in Europe/London using the award timestamp, not task
  due/completion dates; ties share rank (1, 1, 3). Spending never lowers scores.
  Balances, goals,
  job details, request history and ledger entries keep their existing privacy.
  Disabling sharing immediately restores personal-only child progress. Adults
  can always see the household overview. No cross-household board is available.
- Adults can add points to an unfinished shared task assigned to an active
  household child, or create a reward job from Rewards (the same shared-task
  domain, not a second chore system). Personal tasks cannot earn points.
  No open-job claiming is implemented; each job has a named child.
- Completion from either Tasks or Rewards moves the job to waiting for approval.
  An adult approves once or sends it back with a helpful note. Sending back
  reopens the task. Reopening an approved task does not award points again.
  Point/assignee changes are restricted once submitted; use a new task for a
  different child or a new earning opportunity.
- Current jobs exclude past-due jobs, shown separately under Earlier jobs.
  Approved/closed jobs live in progress history, not an overdue list. Adults can
  reschedule a task or explicitly close a job without points (also completing
  the task so it leaves the calendar). One-off jobs never repeat; recurring jobs
  follow the interval and missed-task policies below.
- Points are a household-local ledger, not money. Household row locking
  serializes balance checks and transitions on SQLite/PostgreSQL; database unique
  constraints prevent duplicate awards/reservations/refunds. A request reserves
  its snapshot cost immediately, approval consumes the reservation, and decline
  with a helpful note returns it once. Double submission is idempotent.
- Rewards can be paused/edited, not deleted through the UI. Requests retain their
  original title/cost. Goals reference the current available reward and show
  spendable points (pending reservations excluded).
- Removing a member or deleting an account detaches membership attribution,
  closes outstanding reward jobs and resolves pending requests; rejoining never
  inherits the departed membership's points. Deleting a task/list closes its
  unfinished reward job and detaches the task, retaining approved point history.
  Whole-household deletion removes all reward records child-first.

## Recurring chores (implemented)

- Reward job setup can select several active children, either automatically
  assigning each their own task or offering each an optional claim. These are
  independent per-child series, not a race for a single shared award. Each
  child's turn has its own completion, approval, points and missed history.
  Stopping one child's series does not stop another child's.
- Optional jobs must be claimed by the eligible child before anyone can submit
  their task for approval. Claiming is idempotent and awards no points. Repeats
  require a fresh claim each interval; expired and future intervals cannot be
  claimed. The selected missed-task policy also applies to unclaimed turns.
  Adults cannot claim on behalf of a child, and siblings cannot claim each
  other's turns. All transitions use the household reward lock and scoped queries.
- Tasks & lists and reward jobs use the same daily/weekly recurrence. Existing
  tasks remain one-off. Start with today or a future date; daily intervals follow
  London calendar dates and weekly intervals run Monday-Sunday (due on Sunday).
  An occurrence cannot be completed before its interval begins.
- Each interval has its own persistent task and optional reward job, completion,
  review and ledger award. Pending approval does not block the next interval and
  can be approved later. Weekly scores use the approval date, not the chore date.
- Choose the missed-task policy per series: record an unsubmitted interval as
  not completed with no late points, or retain it for later completion. Nothing is
  deducted for missed intervals. Submitted work is never silently expired.
  Past no-late-point submissions can be approved or closed, not sent back.
- Occurrences through the current interval are materialised when authorised
  task, reward or calendar views are accessed, under the household reward lock.
  Refreshing does not duplicate occurrences or award points; a unique series/date
  constraint is a backstop. Future calendar occurrences are not pre-generated.
- The original task controls stopping the series. Series details, assignee, points,
  interval and missed-task policy are fixed to retain agreed history; stop and
  create a new series to change them. Individual occurrence details can be edited
  without changing future occurrences. Stopping is final: create a new series
  to restart. Occurrences cannot be
  individually deleted/recreated for extra points. Deleting a list removes its
  tasks while retaining detached reward ledger history. A reward assignee leaving
  stops future repeats.

## Future enhancements and external sharing (not implemented)

Cross-household sharing will use invitations to specific items, with acceptance
and revocation. It must not grant household membership, Finance access or access
to unrelated records. Children will not administer external sharing.

Behaviour ratings, streaks, cash/pocket-money rewards and external sharing are not available. Existing Finance childcare records are unrelated
to managed-child sign-in accounts. The previous JonesHQ hub is a feature
reference only; its test data, authentication and styling are not being imported.
