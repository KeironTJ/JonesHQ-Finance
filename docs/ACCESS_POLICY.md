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
local role or module grant is incorrect. Household Hub is still coming soon;
children can currently use Central Hub, appearance and sign-in security.

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

## Planned calendar and external sharing (not implemented)

The first Household Hub feature will be a manual calendar with month and agenda
views, all-day/timed events and the `Europe/London` timezone. Later meal planning,
activities and dated tasks can contribute items.

- Shared and private events have explicit visibility. Adult-private events are
  creator-only; child-private events are visibly labelled as accessible to the
  child and designated guardian.
- Edit and delete permissions are separate: creator-only, selected members or
  all household members. Owners retain management of shared events, never an
  override of someone else's private items.
- Cross-household sharing comes later through invitations to specific items,
  with acceptance and revocation. It must not grant household membership,
  Finance access or access to unrelated records. Children will not administer
  external sharing.

No calendar records, guardian visibility into calendar content or external
sharing exist in this release. Existing Finance childcare records are unrelated
to managed-child sign-in accounts. The previous JonesHQ hub is a feature
reference only; its test data, authentication and styling are not being imported.
