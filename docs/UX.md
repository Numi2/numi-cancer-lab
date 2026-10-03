# Research workspace

The workspace has five views: Overview, CT viewer, Evidence, Match review, and
Saved experiments. They use the existing patient records, forecast engine,
registration artifacts, and local SQLite experiment store. No new service,
frontend framework, cloud dependency, or hosted job is introduced.

## Evidence and experiment state

The header shows the loaded patient and evidence protocol. Editing a field does
not silently replace the loaded observations or delete the current experiment.
Apply settings to start a new draft, or discard edits to return to the loaded
protocol. Saved experiments remain available in their own view. The history list
is scoped to the selected patient and protocols at or before the loaded cutoff.
It is paginated and does not include outcome values.

Seal forecast saves all three numerical baselines. A second save is disabled for
that active experiment. Revealing follow-up requires a separate confirmation.
Resume restores the original saved snapshot and any previously recorded
assessment; it neither recalculates a forecast nor implicitly reveals a new scan.
Requests that time out during a save are not automatically retried. Check saved
experiments before submitting another save.

Unknown burden stays unknown. Forecast spheres appear only beside the last
observed examination used to position them. They are not drawn over older or
revealed examinations in different, unregistered coordinate frames. Exact chart
values are available in a data table. Spheres still encode volume, not anatomy.

## CT inspection

Images load when the CT view is opened, not on every workspace render. Window
presets, numeric display controls, mask opacity, per-plane stepping, and an
expanded dialog reuse the source-slice API. Display size accounts for physical
pixel spacing, including in the expanded viewer. Previous requests are cancelled
and late responses cannot overwrite a new examination. A pending update is
labelled; an error hides the stale image rather than displaying it as current.

The disconnected state explains local setup. No synthetic CT image is substituted
for a missing patient scan. The optional browser-test voxel fixture is explicitly
labelled synthetic. Oblique grids, source-file verification, and the original
research-only imaging limits are unchanged.

## Evidence and correspondence review

Search and sort lesion observations, then open a detail dialog for volume,
position, source reference, full hash, and earlier records with the same identifier.
Unverified repeated identifiers are not described as confirmed tracks.

Match review accepts a locally generated proposal JSON file up to 2 MB. The local
API reproduces its registration and candidates against the selected patient and
checks the explicitly loaded cutoff. The original JSON text is preserved for
verification: JavaScript number normalization must not change a sealed artifact's
float/int representation. Nothing is preselected. Reviewers choose one-to-one
pairs and supply a written reason, their identifier, and an availability day.

Export returns a validated **review draft**, not modified observations. The
existing `review-tracks` command must still check the original import manifest
before generating a new manifest for re-import. Editing the evidence context asks
before discarding unsaved decisions. Closing the browser warns about an unexported
review draft. Drafts and patient content are not stored in browser local storage.

## Mobile and keyboard use

Small screens use compact, expandable evidence settings and five visible view
buttons. A bottom action bar keeps the current forecast action reachable in
Overview. Inputs use mobile-readable type sizes. The lesion table scrolls within
its panel rather than expanding the whole page. CT planes stack vertically.

Use `/` to focus patient search and `?` for help when not editing a field. Workspace
tabs support Left/Right and Home/End, with a single tab stop. Native dialogs close
with Escape, contain focus, and return focus to the initiating control. All
shortcuts have visible alternatives. Focus outlines, status announcements,
reduced-motion preferences, and higher-contrast preferences are supported. These
are implementation checks, not a claim of formal accessibility certification.

## Local verification

```bash
python scripts/check_local.py --browser
python scripts/browser_smoke.py --offline --scan-fixture
```

The browser suite exercises the actual UI code against an in-process API. It
checks explicit reveal, duplicate-save prevention, saved-work recovery, dirty
settings, evidence search, dialogs, candidate review/export, lazy image loading,
late patient responses, and layouts at 320, 390, 768, and 1440 pixels. Offline mode
bundles modules in memory; it is not live TCP, native module-loading, or CSP runtime
verification. API tests retain checks on the production security headers.

Chromium responsive testing is not a physical iPhone or Safari qualification.
Synthetic voxel tests do not validate actual NIfTI ingestion or clinical data.
No hosted CI is installed or invoked.

Implementation references: W3C WAI-ARIA APG tabs and modal-dialog patterns, and the
standard AbortController interface. The application requires no remote assets.
