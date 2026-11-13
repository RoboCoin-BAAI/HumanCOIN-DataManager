# Release checks

## Included

- `docs/`: static portal, bilingual UI, compact catalog, immutable details and preview assets.
- `scripts/` and `sync-state/`: public metadata sync, incremental cache and preview generation.
- `tests/`: catalog, sync and preview tests; optional Firefox browser checks.
- `.github/workflows/`: Pages deployment and scheduled catalog refresh.
- Scene vocabulary, design notes and English/Chinese documentation.

Original design HTML, reference screenshots, local agent settings, credentials and Python caches are excluded.

## Validation

Run from the repository root:

```bash
npm test
npm run check
```

Browser review: dismiss the welcome notice; switch English/Chinese; check scene hierarchy, task search, pagination, selection and command generation. Dataset content and commands must remain unchanged across languages. Hover autoplay depends on browser policy; manual preview remains available.

## Hosting

1. Set Settings → Pages → Source to GitHub Actions.
2. Confirm Actions is enabled and the deployment workflow succeeds.
3. Visit https://robocoin-baai.github.io/HumanCOIN-DataManager/ and test a fresh session.
4. Confirm the scheduled catalog workflow can commit to main under repository branch rules.

## Current access behavior

The bundled catalog records the two current Hugging Face datasets as public and not gated. Access-request notices are conditional guidance; actual gating must be configured on the platform. Full-video previews reference upstream URLs and have no automatic cross-platform fallback. A gated upstream video may require authentication and fail in the portal; do not put private tokens in the frontend.
