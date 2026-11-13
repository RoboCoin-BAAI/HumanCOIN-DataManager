# Visitor controls audit

Date: 2026-11-13. Scope: current buttons, input controls, dialogs and redundant visitor UI. Autoplay permission investigation was stopped at the user's request; no new autoplay features were added for this audit.

## Verified behavior

The audit uses a real, isolated Firefox profile and 45 synthetic repositories with varied tiers, scenes, tasks, modalities, resolutions and source availability. JSON export is downloaded as an actual file and imported through the browser's file input. It does not download full datasets or change the user's clipboard.

| Area | Checks |
| --- | --- |
| Navigation | Overview, Explore, My Selection, documentation, About; dialogs close with their close button, Escape and overlay click |
| Discovery | Initial failure/retry; All levels and tier selection; combined scene/task/resolution filters; AND modality matching; search; reset retains selected tiers |
| Ordering and pages | Default order, newest, episodes, downloads; 20/50/100 page sizes; previous/next; one-page controls disabled/hidden appropriately |
| Selection | Individual, current page and all matching records; cross-page selection; selection panel paging; remove/clear; empty-state actions disabled |
| Export/import | Actual JSON download and file-input round trip; file-picker delegation; invalid JSON and missing IDs preserve existing selection; changed revisions require explicit confirmation |
| Downloads | Single/batch commands, source switching, unavailable-source feedback; commands use current catalog revisions |
| Copy | Generated text reaches the clipboard API boundary correctly; rejected API and throwing legacy-copy fallback show a useful message without an unhandled error. The real OS clipboard is not modified by the test |
| Preview | Clickable cover and keyboard entry; detail dialog; camera selection, failed camera to valid camera status recovery; detail-to-download action |
| Updates | No-update check, failed check and retry preserve selection; separate existing regression covers new-snapshot preparation, failed-refresh rollback and successful atomic replacement |
| Rapid actions | A late bulk-select result cannot override a newer Clear action. Restoration/import have revision guards so late results cannot overwrite newer selection edits |

External link destinations are checked in the source. Platform authentication, access approval, actual large dataset transfers and clipboard behavior under each visitor's OS/browser permissions are outside this audit.

## Issues fixed

1. Informational toasts could cover the Copy Command button and intercept clicks. They no longer receive pointer events.
2. Clipboard API rejection followed by an exception from the legacy copy fallback produced an unhandled rejection. Both failure paths now show the manual-copy message.
3. Switching from a failed camera did not clear its previous failure status. A new camera now resets the message and reports readiness once data loads; event handlers retain their own status element instead of looking up a possibly replaced dialog.
4. In-flight Select all, import and saved-selection restoration could overwrite later selection edits. These operations now check selection revision (and snapshot where applicable).
5. After an initial catalog failure, a later scope retry could still invoke full initialization. Retry is restored to the scope operation after initialization succeeds.
6. Worker errors now terminate the failed worker and reject future requests, rather than leaving a retry waiting indefinitely. Initialization can create a fresh worker.
7. Import is disabled during initial catalog loading; Clear is disabled for an empty selection.

## Redundant or misleading UI removed

- **Public only:** sync already excludes private repositories, so toggling it did not alter the published catalog. The filtering primitive remains available in the data layer, but the useless visitor checkbox is removed.
- **Featured:** there is no editorial recommendation/ranking system. The existing stable sort is labeled **Default order**.
- **Duplicate Preview buttons:** the cover is now a keyboard-accessible click target, with one explicit Preview button in the action column.
- **Fixed tier progress bars:** the original 42%/68%/87% widths were decorative, not measured publication statistics. They are removed.
- **Select page on a single page:** hidden when its result would be identical to Select all matches; retained for multi-page results.
- **Unused selectionPayload helper:** removed.

Pagination, cross-page selection, import/export, source selection, source-specific command validation and update checking are retained. They serve distinct needs and remain useful as the catalog grows.

## Reproduce

```bash
npm test
npm run check
geckodriver --host 127.0.0.1 --port 4444
# Separate terminal, same repository:
python3 tests/browser_buttons.py
python3 tests/browser_smoke.py
```

`browser_buttons.py` creates and cleans a temporary folder in the workspace so the Firefox Snap can access download/upload files. The smoke test uses a separate temporary site. Neither modifies the real catalog or sends messages to external services.
