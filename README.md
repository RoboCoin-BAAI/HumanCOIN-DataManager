# HumanCOIN DataManager

[简体中文](README_zh-CN.md) · [Release checks](RELEASE_CHECK.md)

A static portal for discovering, filtering, previewing and downloading HumanCOIN datasets from [Hugging Face](https://huggingface.co/HumanCOIN) and [ModelScope](https://www.modelscope.cn/organization/HumanCOIN). It preserves the supplied HTML design and follows the catalog/selection/download workflow of RoboCOIN-DataManager.

The acquisition tiers follow the [HumanCOIN project introduction](https://koorye.github.io/HumanCOIN-dev/): L1 visual intention, L2 motor intention and L3 cognitive intention. Actual modalities and statistics come from repository metadata, rather than the project’s planned scale.

## Run locally

Python 3.10+ and Node.js 20+ are required for development and tests. There are no frontend packages to install.

```bash
npm run dev
```

Open http://127.0.0.1:8000/ . Use HTTP; opening the HTML directly will not support module workers or catalog requests.

## Browsing and pagination

The initial page reads `data/catalog.json`, then automatically loads the first page of one browsing scope. A valid shared-link scope takes priority; otherwise the portal restores the last browsed scope. First-time visitors use `DEFAULT_LEVEL` in `docs/js/config.js` (L1 by default), falling back to the first nonempty tier. Currently only L3 contains published data, so it opens automatically. Empty remembered scopes fall back too; an explicitly linked empty tier remains selected. The default scope is recorded in the URL without adding a history entry. Choose another tier, multiple tiers or **All levels** to change scope; the portal never silently loads every tier for a first visit.

The former device-type filter is replaced by **Main camera resolution** (for example, `1920 × 1184`). Resolution comes from the explicitly declared primary camera metadata; repository names such as `left_1920x1184` are a fallback. Master-timeline and wrist-camera sizes are not substituted for a missing primary camera.

The selected scope must finish loading before final counts or “Select all matches” become available. A module Web Worker verifies content hashes, parses indexes, filters the complete scope, applies stable sorting, computes matching statistics and returns one page. Default page size is 20; 50 and 100 are also available. Changing filters resets to page 1. URL parameters preserve scope, filters, sort and page for navigation and sharing.

**Select page** and **Select all matches** are separate actions. Selection survives tier/page changes and is itself displayed in 20-item pages. Browser storage saves IDs, tier hints and source revisions. JSON import validates all relevant tiers before changing the selection; older files without tier hints require checking all tiers. Imports with changed revisions offer an explicit review step.

Cards display small real-video posters, lazy-loaded near the viewport. Real mouse hover over any part of a dataset card starts a muted, looping 4-second preview after 300 ms, including in embedded/hybrid browsers whose CSS hover capability is inaccurate; at most one card plays. Leaving the card, starting to scroll, changing pages, opening a modal or hiding the tab stops and unloads the clip. Hover playback stays blocked during scrolling; after scrolling has been idle for 180 ms, a still-hovered card starts a fresh 300 ms hover delay. Normal page surfaces use lightweight backgrounds rather than per-card or fixed-sidebar backdrop blur; blur is limited to the open modal overlay. Reduced-motion and data-saving preferences disable hover playback. Touch devices use the Preview button. Full videos and sensor metadata are still loaded only when Preview is opened; cards never preload clips before hover. Detail requests are shared and up to 100 successful details are kept in memory. Download commands and JSON exports use compact index revisions and do not fetch every selected dataset’s details. Search covers ID, task, scene, modality and short summary, not the full detail document.

## Snapshot files and statistics

```text
docs/data/catalog.json                   current summary, counts and tier references
docs/data/manifests/<snapshot-id>.json    retained immutable snapshot manifests
docs/data/indexes/<tier>/<hash>.json      compact tier shards
docs/data/details/<hash>.json             static sensor/video/description details
docs/data/reports/<hash>.json             detailed metadata warnings
docs/data/media/<hash>.jpg|mp4            generated posters and short clips
docs/data/retention.json                 last-seen dates for snapshot retention
sync-state/                             public source metadata cache and removal state
```

Schema version is **3**. A tier starts with one index file and splits by stable ID-hash prefixes when a shard would exceed 2 MiB. These storage shards are independent of UI pages. New immutable files are staged and validated before the current manifest pointer changes. All snapshots from the last seven days and at least the latest two content snapshots are retained. Referenced indexes and details are retained with them. A no-change sync preserves the content snapshot ID and generation time while updating check time.

Global and per-tier statistics are computed by the sync process. Homepage cards keep the global totals and do not depend on which indexes a visitor has loaded. Matching-scope statistics are computed from all matching records before paging.

Counts use distinct repository IDs. Matching IDs on HF/MS merge into one catalog entry; this does not prove identical content. Distinct recording/configuration variants remain distinct repositories. Episode counts and duration are repository totals and may overlap. Duration uses declared seconds or a marked master-frame/fps derivation; source streams are not summed. Size is repository-declared bytes. Downloads represent the HF API field, not a combined cross-platform or real-time download count.

Each aggregate records known, missing, stale and derived counts. Missing is not zero; entirely missing totals show `—`, partial totals are labeled, and invalid negative/non-finite counts are excluded. Unknown tiers stay in an explicit bucket. Platform conflicts and metadata failures appear in the quality report.

## Sync and validate

```bash
npm run sync
python3 scripts/sync_catalog.py --validate
# Re-read unchanged metadata when diagnosing a source change:
python3 scripts/sync_catalog.py --force
```

The standard-library sync script paginates both public platform inventories. HF content commits and ModelScope modification fingerprints avoid re-reading unchanged metadata. Branch-based metadata is checked at least daily; HF commit-based metadata is reused until its commit changes. Download counts and availability update independently of content revisions. Both platforms have metadata adapters; fresh HF metadata takes priority, then fresh MS, then available stale metadata.

Default concurrency is 4 (`--workers 1` through `8`). Requests have bounded retries, exponential backoff/jitter, Retry-After handling and reduced concurrency after 429 responses. Missing/failed metadata preserves a previous successful source cache as stale. If either inventory is incomplete, no new snapshot is published. A source disappears only after two consecutive complete inventories confirm absence; the first absence is marked as a removal candidate and cannot generate a download command for that source.

`sync-state/` contains only public normalized metadata. Commit it along with `docs/data/` so CI has durable incrementality and removal state. Deleting this cache safely causes metadata to be fetched again; do not add credentials to it. Concurrent sync invocations against the same output should be serialized; the scheduled workflow already serializes refresh jobs.

HF and MS same-name metadata conflicts are reported rather than added together. A source exposing only a main/master branch has a mutable reference; such downloads cannot promise historical reproducibility. No hub credentials or full dataset snapshots are stored by this website. Sync uses FFmpeg to generate a 480-pixel-wide JPEG poster and a 4-second, 12-fps muted MP4 preview from the first RGB stream. These small assets are content-addressed, shared when identical, validated and retained with their snapshots. Generation is cached per source URL/version and bounded to 50 new previews per sync; use `--preview-limit N` to change the budget (0 reuses cache only). Missing FFmpeg or failed media extraction is reported without breaking catalog browsing. FFmpeg is required to generate new assets, but is not required to serve already-generated assets; the scheduled workflow installs it if missing.

## Visitor refresh

Browsing is pinned to one content snapshot. The visible page checks only the small manifest at most every five minutes and offers a manual **Check for updates** action. Hidden tabs do not poll.

A new snapshot displays **New catalog available · Refresh**. It does not replace the current list automatically. Clicking Refresh prepares the required new scope, revalidates selected IDs (across tiers, since tier assignments can change), then switches the manifest/results/selection together. Failed refreshes retain the previous complete snapshot. Removed selections, version changes and source unavailability are reported. Cached old snapshots whose files have expired show an actionable load error instead of mixing versions.

## Download tool

Install the implemented CLI from [HumanCOIN-LeRobot](https://github.com/RoboCoin-BAAI/HumanCOIN-LeRobot):

```bash
git clone https://github.com/RoboCoin-BAAI/HumanCOIN-LeRobot
cd HumanCOIN-LeRobot
pip install -e ".[download]"
# For ModelScope:
pip install -e ".[modelscope]"
```

Select repositories and a source, then copy generated commands. Each repository has its own `--revision`; add `--dry-run` to inspect destinations. Use the platform’s approved authentication mechanism for restricted datasets. `selection.json` is for restoring website selections, not a `--manifest` CLI input.

## Checks

```bash
npm test
npm run check
```

Tests cover 10,001-record queries, exact paging, stable sorts, tier-only loading, request deduplication, integrity failures, detail caching, cross-tier selection, partial statistics, incremental metadata reuse, stale fallback, confirmed removals, atomic publication, retention and inventory failure preservation. `npm run check` also validates every reference, hash, tier count and aggregate in the real snapshot.

Optional Firefox regression (standard-library WebDriver client; uses a temporary site and synthetic metadata):

```bash
geckodriver --host 127.0.0.1 --port 4444
# In another terminal:
python3 tests/browser_smoke.py
python3 tests/browser_buttons.py
```

These check actual module workers, 20-row pages, cross-page selections, URL history, on-demand details, failed-update rollback, successful snapshot/selection switching, button/navigation flows, actual JSON downloads/uploads, copy failures and source validation. Findings and UI simplifications are recorded in [design/button-audit.md](design/button-audit.md). Capacity experiments and the design rationale are in [design/catalog-architecture.md](design/catalog-architecture.md). Synthetic benchmarks do not establish performance on low-end phones; large scopes remain bounded by browser memory and may eventually require a server search API.

## GitHub Pages

Push this project to your repository and select **GitHub Actions** under Settings → Pages → Source. `main` is the configured publication branch.

- `pages.yml` tests, validates and deploys the complete `docs/` directory.
- `catalog.yml` refreshes daily at 09:00 Asia/Shanghai or manually, tests/validates, commits the complete `docs/data/` and `sync-state/`, and deploys those artifacts with their matching source commit. Actions needs repository write access; protected branches may need a repository-specific PR workflow.

No remote push or live deployment is performed during local development. The supplied HTML, PNG samples and RoboCOIN reference checkout remain local reference materials and are excluded from the new repository by `.gitignore`.

Scene filters use the category → area hierarchy in `HUMANCOIN_SCENES_V1.md` and `humancoin_scenes_v1.json`. The six categories and two fallback categories are fixed; new areas can be declared under an existing category. Known areas are mapped to their specified category, while unrecognized legacy areas remain available without an inferred category. Sync preserves both fields in the compact index. Existing upstream metadata is not rewritten.

Task selection supports text search within the current scene and other filters. The worker returns at most 100 matching task candidates and a total count, while dataset filtering and pagination still cover all matching records. Searching task candidates does not select a task or change dataset results until a task is chosen. The current task remains selected when it falls outside the candidate window.

The portal supports English and Chinese UI through the language button in the top bar. Use `?lang=zh` for a direct Chinese link or `?lang=en` for English. The browser remembers the selected language. Dataset names, task and scene values, metadata, repository IDs and download commands remain in English.
