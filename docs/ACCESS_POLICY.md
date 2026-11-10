# Household access and managed child accounts

## Implemented access layers

1. **Account identity:** authentication, active account and adult/managed-child
   status. Managed-child status belongs to the account, not a household.
2. **Household membership:** the selected membership determines the household,
   owner/member role and local access choices. `family_id` remains the hard
   boundary between households.
3. **Module access:** `HouseholdMembership.allowed_modules` grants `finance`
   and/or `household`. Household owners manage these under Central settings,
   **Household module access**, independently for each membership.
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

An active household owner can create a **new** managed-child account from the
module-access page, providing an account name, unique sign-in email and an
initial password meeting the normal password policy. The creating owner becomes
the designated guardian. Existing adult accounts cannot be converted or taken
over. Child creation does not bypass normal sign-in/email-verification controls.

Children start as members with Household Hub allowed, no Finance grant and no
Finance sections. Finance, household administration, self-joining households,
self-deletion and operator tools remain blocked across households even if a
local role or module grant is incorrect. Children can use the Household Hub
calendar, Central Hub, appearance and sign-in security.

Only the designated guardian can transfer guardianship or release the account
into an adult account, under Central settings, **Managed child accounts**.
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
created all-day/timed events in `Europe/London`. Meal plans and approved activities
also contribute source-linked items; dated-task feeds are future work.

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

## Future feeds and external sharing (not implemented)

Cross-household sharing will use invitations to specific items, with acceptance
and revocation. It must not grant household membership, Finance access or access
to unrelated records. Children will not administer external sharing.

Task feeds and external sharing are not available. Existing Finance childcare records are unrelated
to managed-child sign-in accounts. The previous JonesHQ hub is a feature
reference only; its test data, authentication and styling are not being imported.
