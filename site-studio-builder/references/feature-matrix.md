# Feature matrix — Studio ↔ skill templates

This table maps every module in the proven Studio implementation to the skill
document/template that reproduces it. Use it as a checklist when applying the
skill to a new site: tick each row until the skill's output matches the Studio
feature-for-feature.

## Studio → skill map

| Studio module (medkungfu-clone-proof) | Skill location | Purpose |
|---|---|---|
| `src/lib/i18n/translations.ts` (flat dotted keys) | SKILL.md "DOM-injected clones" §1 | Faithful text-key baseline (en/zh/ru). |
| `.content/translations.json` + `pages/*.json` + `navigation.json` + `meta.json` | SKILL.md Step 2, architecture.md §4 | UCD on disk, first-run-only seed. |
| `scripts/seed-ucd.ts` | SKILL.md Step 2, architecture.md §4 | Writes `.content/` from baseline modules. |
| `_gen_blocks.py` | **scripts/gen-blocks.py** | Split injected HTML into page blocks → `public/studio-blocks/*.json`. |
| `src/lib/executor/content-runtime.ts` | architecture.md §1 | Module singleton: `translate`/`getSectionData`/`commitDocument`. |
| `src/lib/executor/use-content-runtime.ts` | architecture.md §5 | React bridge (`useSyncExternalStore`) + SSR-safe fallback. |
| `src/lib/content/compat-adapter.ts` | architecture.md §2 | `compatTranslate` merge policy (base + override). |
| `src/lib/content/content-loader.ts` (mtime cache) | architecture.md §6 | Cross-instance cache correctness. |
| `src/lib/i18n/apply-overrides.ts` | architecture.md §7 | Swap edited text + image keys back into injected HTML. |
| `src/lib/i18n/has-page-edits.ts` + `src/components/InteractiveTier.tsx` | architecture.md §8 | Per-page interactivity vs editing. |
| `src/components/ContentBootstrap.tsx` | architecture.md §3 | Reconnect edits to public pages (skip `/studio`). |
| `src/components/StudioFab.tsx` + `.studio-fab` CSS | architecture.md §9 | Env-gated floating entry button (own globals.css styles). |
| `src/lib/studio/developer-gate.ts` | architecture.md §10 | `isDeveloperRequest()` — bound across button/routes/API. |
| `src/lib/puck/puck-adapter.ts` | **puck-canvas.md §1** | `ucdToPuck`/`puckToUcd`/`sanitizeKey`/`baselineValue`/`baselineImage`/`resolveBlockTitle`. |
| `src/lib/puck/puck-config.tsx` | **puck-canvas.md §2** | `PageBlock` + `buildPageConfig`. |
| Puck `data` prop + `PuckDataBridge` | **puck-canvas.md §3a** | Push data into Puck's store (init-only prop pitfall). |
| Dot-key sanitize (`sanitizeKey`) | **puck-canvas.md §3b** | Dot→`__` so Puck treats keys as flat props. |
| `viewports` desktop (1280) | **puck-canvas.md §3c** | Avoid 360px default; render the whole page. |
| `StudioOutline` (`overrides.outline`) | **puck-canvas.md §4** | Custom block outline with resolved titles. |
| `src/lib/puck/custom-field-types.tsx` (ImageField) | **puck-canvas.md §5a** | Image field type. |
| `src/app/api/studio/upload/route.ts` | **puck-canvas.md §5b** | Multipart upload, 5MB, 400 on empty body. |
| `src/lib/studio/asset-store.ts` | **puck-canvas.md §5c** | Save + index uploaded images. |
| `src/app/api/studio/uploads/[path]/route.ts` + rewrite | **puck-canvas.md §5d** | Serve runtime uploads (build-time snapshot limitation). |
| Image keys `{slug}__{blockId}__img{n}` | **puck-canvas.md §5e** | Slug-prefixed image keys (no cross-page collision). |
| `src/lib/studio/page-registry.ts` + `/api/studio/pages` | **puck-canvas.md §6** | Authoritative page list from blocks files. |
| `src/app/studio/StudioIndex.tsx` | puck-canvas.md §6 | Navigation page (grouped, real pages only). |
| `src/lib/agent/dom-ops-mapper.ts` | **puck-canvas.md §7** + nl-command-bar.md | Map plan ops → flat keys (1:1 first). |
| `src/lib/agent/path-resolver.ts` (`isRealFlatKey`) | nl-command-bar.md | Resolve flat keys 1:1 (dots literal). |
| `/api/studio/document` (re-read disk) | **puck-canvas.md §8** | Always `loadFullDocument()` (cross-instance). |
| `src/app/studio/components/Toolbar.tsx` | **puck-canvas.md §9** | Minimal toolbar (undo + save), hide Puck header. |
| `src/app/studio/components/ImageUploader.tsx` | puck-canvas.md §5 | Upload + library modal + compression. |

## Default configuration & parameters

Align these defaults so behavior is identical to the proven Studio:

| Parameter | Value | Where |
|---|---|---|
| Puck viewport | `[{ width: 1280, height: "auto", icon: "monitor", label: "Desktop" }]` | `<Puck viewports=…>` |
| Puck `overrides.iframe` | default (iframe on) — do NOT set `enabled:false` | `<Puck>` |
| Puck `overrides.header` | `<PuckDataBridge/>` (renders nothing, hides Puck's own toolbar) | `<Puck>` |
| Puck `overrides.outline` | `<StudioOutline/>` | `<Puck>` |
| Puck `overrides.fieldTypes` | `{ image: ImageField }` | `<Puck>` |
| Upload max size | **5 MB** (server) | `asset-store.ts` `MAX_SIZE_BYTES` |
| Upload MIME whitelist | jpeg, png, webp, svg+xml | `asset-store.ts` `ALLOWED_MIME` |
| Client compression threshold | **500 KB** raster (skip SVG) | `ImageUploader.tsx` |
| Client compression params | `maxSizeMB: 1`, `maxWidthOrHeight: 1920`, `useWebWorker: true` | `ImageUploader.tsx` |
| Upload storage path | `public/uploads/studio/YYYYMM/<sha256-16>.<ext>` | `asset-store.ts` |
| Upload URL | `/uploads/studio/YYYYMM/<hash>.<ext>` | `asset-store.ts` |
| Debounced save | **1000 ms** | `useDebouncedSave(savePatch, 1000)` |
| Block split tags | `main`, `section` (recursive); `header[role=banner]` | `gen-blocks.py` `SPLITTABLE` |
| Block split max depth | **4** | `gen-blocks.py` `MAX_DEPTH` |
| Block id scheme | `main-0` → `main-0-0`, `main-0-1` → … | `gen-blocks.py` `expand` |
| Image key scheme | `{slug}__{blockId}__img{n}` | `gen-blocks.py` `images_in_seg` |
| Developer gate (soft) | `NEXT_PUBLIC_SHOW_STUDIO_FAB === "true"` in prod | `developer-gate.ts` |
| Developer gate (hard) | loopback host only (`localhost`/`127.0.0.1`/`[::1]`) | `developer-gate.ts` |
| Studio route gate | `notFound()` → 404 when denied | `/studio/page.tsx`, `/studio/[page]/page.tsx` |
| API gate | `NextResponse.json(..., { status: 404 })` on every `/api/studio/*` | all studio routes |
| Seed policy | first-run-only (skip if `translations.json` exists) | `seed-ucd.ts` |
| Editable pages | `export const dynamic = "force-dynamic"` | every page component |
| gitignore additions | `.content/`, `versions/`, `public/studio-blocks/`, `public/uploads/`, `public/*.chunk.js` | host project |
