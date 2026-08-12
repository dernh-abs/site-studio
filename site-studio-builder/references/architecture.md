# Architecture — Site Studio Builder

Detailed file map, data flow, and the **verified** code patterns extracted
from a working implementation (Next.js 16 + React 19 + Puck 0.20). Use these as
the concrete templates when scaffolding a new studio.

## Data flow

```
                 .content/ (gitignored, runtime)
                 translations.json / pages/*.json / navigation.json / meta.json
                          │  (read by)
                          ▼
   Studio writes ──► LocalContentStore.writeAtomic ──► .content/* (patched)
                          │                                     │
                          │                          /api/studio/document
                          ▼                                     │ reassembles
   /studio (Puck, client) ◄── edits applied ───────────────────┘ into UCD
          │
          │  (public pages read through)
          ▼
   ContentBootstrap (public only, skips /studio)
          │  fetch /api/studio/document → commitDocument()
          ▼
   ContentRuntime.doc  ──► translate() / getSectionData()  ──► components (t(), useSectionData)
          │                                              │
          │ when doc === null                            │ fallback = module (TRANSLATIONS/RU)
          ▼                                              ▼
   Public site renders faithfully even before any edit  (merge: module base + UCD override)
```

## File map

| File | Responsibility |
|------|----------------|
| `src/lib/i18n/translations.ts` | Faithful baseline copy (en+zh), nested `translation` dict. **Base dictionary.** |
| `src/lib/i18n/ru.ts` | Russian flat map `enText → ruText`. **Base dictionary.** |
| `src/lib/content/seed-data.ts` | Structured section data (`HOME_PAGE_SEED`, `NAVIGATION_SEED`, `PLACEHOLDER_PAGES`). SSR fallback source. |
| `src/lib/content/content-schema.ts` | `UnifiedContentDocument`, `Translations` types. |
| `scripts/seed-ucd.ts` | Build-time seed → writes `.content/*`. **First-run only.** |
| `src/lib/executor/content-runtime.ts` | Module singleton holding `doc`; `translate`, `getSectionData`, `commitDocument`, `subscribeRuntime`, `getSnapshot`. |
| `src/lib/executor/use-content-runtime.ts` | React bridge (`useSyncExternalStore`) + `useSectionData(page, id, fallback)`. |
| `src/lib/content/compat-adapter.ts` | `compatTranslate` with **merge** policy; `fallbackTranslations()`. |
| `src/lib/i18n/apply-overrides.ts` | **DOM-injected baseline only**: swap edited values (flat dotted keys) back into injected HTML. |
| `src/lib/i18n/has-page-edits.ts` | **DOM-injected baseline only**: does the UCD hold any override for a slug vs the baseline module? |
| `src/components/InteractiveTier.tsx` | **DOM-injected baseline only**: server component — injects the original JS bundle on pages with NO edits, returns null on edited pages (per-page interactivity). |
| `src/components/ContentBootstrap.tsx` | Client loader: fetch `/api/studio/document`, `commitDocument`, skip `/studio`. |
| `src/app/layout.tsx` | Mounts `<LanguageProvider><Children/><StudioFab/><ContentBootstrap/></LanguageProvider>`. |
| `src/app/api/studio/document/route.ts` | Assembles `.content/*` → UCD. |
| `src/lib/content/local-content-store.ts` | Atomic writes of patch ops → `.content/*`. |
| `src/app/studio/**` | Puck editor: `NLCommandBar`, `IntentPreview`, `PuckEditor`, `PendingPreview`. |
| `src/app/api/studio/patch/route.ts` | RFC-6902 patch → `LocalContentStore`. |
| `src/app/api/agent/command/route.ts` | NL command → intent/operations/answer/templates/error. |
| `src/lib/agent/rule-matcher.ts` | Maps NL text → rule (e.g. `query.help` → capability). |
| `src/components/StudioFab.tsx` | Env-gated floating "Edit in Studio" button. |

## Verified code patterns

### 1. ContentRuntime — module singleton

```ts
// src/lib/executor/content-runtime.ts
import { compatTranslate, fallbackTranslations } from "@/lib/content/compat-adapter";
import { subscribe, notifySubscribers } from "./notify";

let doc: UnifiedContentDocument | null = null;
let snapshotVersion = 0;

export function setDocument(next: UnifiedContentDocument | null): void {
  doc = next;
  notifySubscribers();
}
export function getDocument(): UnifiedContentDocument | null { return doc; }

export function translate(lang: SupportedLanguage, key: string): string {
  const translations: Translations | null = doc?.translations ?? null;
  return compatTranslate(lang, translations, key);
}
export function getSectionData(page: string, sectionId: string): unknown {
  const pageData = doc?.pages?.[page as keyof typeof doc.pages];
  if (!pageData) return null;
  return (pageData as { sections?: Record<string, unknown> }).sections?.[sectionId] ?? null;
}
export function subscribeRuntime(listener: () => void): () => void { return subscribe(listener); }
export function getSnapshot(): number { return snapshotVersion; }

// commitDocument bumps the snapshot so useSyncExternalStore re-renders.
export function commitDocument(next: UnifiedContentDocument | null): void {
  setDocument(next);
  snapshotVersion++;
}
```

### 2. compat-adapter — MERGE policy (the safety net)

```ts
// src/lib/content/compat-adapter.ts
export function compatTranslate(lang, translations, key): string {
  const moduleEn = (TRANSLATIONS.en?.translation as Record<string, unknown>) ?? {};
  // module is the BASE; UCD OVERRIDES per-key. A partial UCD can never break render.
  const enDict = translations?.en ? { ...moduleEn, ...translations.en } : moduleEn;
  const enText = lookup(enDict, key) ?? resolve(enDict, key) ?? key;

  if (lang === "ru") {
    const ruMap = translations?.ru ? { ...RU, ...translations.ru } : RU;
    const v = ruMap[enText];
    return typeof v === "string" ? v : enText;
  }
  const moduleLang = (TRANSLATIONS[lang]?.translation as Record<string, unknown>) ?? {};
  const dict = translations?.[lang] ? { ...moduleLang, ...translations[lang] } : moduleLang;
  if (dict) {
    const direct = lookup(dict, key);
    if (direct !== undefined) return direct;
    const nested = resolve(dict, key);
    if (nested !== undefined) return nested;
  }
  return enText;
}
```

### 3. ContentBootstrap — reconnect edits to public pages

```tsx
// src/components/ContentBootstrap.tsx  ("use client")
import { useEffect } from "react";
import { usePathname } from "next/navigation";
import { commitDocument } from "@/lib/executor/content-runtime";

export function ContentBootstrap() {
  const pathname = usePathname();
  useEffect(() => {
    if (pathname?.startsWith("/studio")) return;   // never clobber the editor's doc
    let cancelled = false;
    fetch("/api/studio/document")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (cancelled || !data?.success || !data.document) return;
        commitDocument(data.document);
      })
      .catch(() => { /* fall back to faithful baseline (doc stays null) */ });
    return () => { cancelled = true; };
  }, [pathname]);
  return null;
}
```

### 4. seed-ucd.ts — first-run-only guard (edits survive restarts)

```ts
// scripts/seed-ucd.ts  (run via npm run seed; called by predev/prebuild)
const CONTENT_DIR = path.join(process.cwd(), ".content");

async function main(): Promise<void> {
  if (validateOnly) { await validateExtractionMap(); return; }

  // First-run only: if .content/translations.json exists, skip so Studio edits
  // (persisted into .content/*) survive `npm run dev` restarts and builds.
  if (fsSync.existsSync(path.join(CONTENT_DIR, "translations.json"))) {
    console.log("[seed-ucd] .content/ already exists — skipping to preserve edits.");
    await validateExtractionMap();
    return;
  }
  // ... write translations.json, pages/*.json, navigation.json, meta.json ...
}
```

### 5. useSectionData — SSR-safe fallback (no hydration mismatch)

```ts
// src/lib/executor/use-content-runtime.ts
export function useSectionData<T>(page: string, sectionId: string, fallback: T): T {
  useSyncExternalStore(subscribeRuntime, getSnapshot, getSnapshot);
  const data = getSectionData(page, sectionId);
  return (data as T | null) ?? fallback;   // doc is null on server → uses seed fallback
}
```

### 6. mtime-validated content cache (Next 16 cross-instance)

Next 16 compiles Route Handlers and page rendering into **separate module
instances**: a cache entry invalidated in-memory by the patch API is invisible
to the page side. Symptom: `/api/studio/document` returns the new value while
the public page still renders the old one. Fix — validate by file mtime on
every read, so both instances agree on disk state:

```ts
// src/lib/content/content-loader.ts
const cache = new Map<string, { mtimeMs: number; data: unknown }>();

async function readJsonFile<T>(rel: string): Promise<T | null> {
  const abs = path.join(process.cwd(), CONTENT_DIR, rel);
  try {
    const st = await fs.stat(abs);
    const hit = cache.get(rel);
    if (hit && hit.mtimeMs === st.mtimeMs) return hit.data as T;
    const parsed = JSON.parse(await fs.readFile(abs, "utf-8")) as T;
    cache.set(rel, { mtimeMs: st.mtimeMs, data: parsed });
    return parsed;
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw err;
  }
}
```

### 7. applyOverrides — DOM-injected baseline renderer

The seed step rewrites each extracted leaf text node in the page's HTML into a
placeholder `{tk:{slug}.{tag}.{n}}` (page.tsx is generated once). The page
renderer substitutes placeholders from the merged dict:

```ts
// src/lib/i18n/apply-overrides.ts
// dict = merged translations for one language (flat dotted keys).
export function applyOverrides(html: string, dict: Record<string, string>): string {
  return html.replace(/\{tk:([^}]+)\}/g, (m, key) => dict[key] ?? m);
  // dict[key] is the ORIGINAL text until the Studio edits it (compatTranslate
  // merges UCD over the base module) -> byte-identical until an edit lands.
}
```

Text-key extraction (seed side): walk the injected HTML with a tree parser,
collect every leaf text node (skip `script`/`style`/`noscript`), assign
`{slug}.{tag}.{n}` in document order, and write both `translations.ts` (flat
base dict) and `.content/translations.json` (first-run-only). Nested markup
(`<h1><span>A</span> <span>B</span></h1>`) yields per-`span` keys — the editor
shows leaf-level strings, never partial mixed nodes. These flat dotted keys
are also the patch paths (`/translations/en/{key}`), so no path translation is
needed in the Studio UI or the patch API.

### 8. InteractiveTier — per-page interactivity vs editing

The bundle's `createRoot()` wipes edited HTML, but only where it runs. Decide
**per page** instead of removing the bundle globally (which would kill
interactivity on every untouched page):

```ts
// src/lib/i18n/has-page-edits.ts
export function hasPageEdits(
  ucdEn: Record<string, unknown> | undefined,
  slug: string
): boolean {
  if (!ucdEn) return false;
  const baseEn = (TRANSLATIONS.en?.translation ?? {}) as Record<string, unknown>;
  const prefix = `${slug}.`;
  for (const key of Object.keys(baseEn)) {
    if (key.startsWith(prefix) && ucdEn[key] !== baseEn[key]) return true;
  }
  for (const key of Object.keys(ucdEn)) {
    if (key.startsWith(prefix) && baseEn[key] === undefined) return true;
  }
  return false;
}
```

```tsx
// src/components/InteractiveTier.tsx  (server component; page.tsx renders it)
export async function InteractiveTier({ slug }: { slug: string }) {
  const doc = await loadFullDocument();
  const ucdEn = doc?.translations?.en as Record<string, unknown> | undefined;
  if (hasPageEdits(ucdEn, slug)) return null;       // edited page: static + overrides win
  return <script defer src="/bundle.e1ad0c10972d.js" />;  // untouched: full interactivity
}
```

Every page adds `<InteractiveTier slug="{slug}" />` (slug derivation mirrors
the seed: `src/app/page.tsx` → `index`, `src/app/ru/about/page.tsx` →
`ru__about`). Safe under plain-`<a>` navigation (full-page loads); an SPA
router could re-enter an edited page from an interactive one and clobber it —
do not use this pattern with a client-side router.

### 9. New-component styles: own globals.css, not clone Tailwind

`cloned-site.css` is the original site's compiled Tailwind and only contains
utilities present in the original HTML. Tailwind classes on new components
(StudioFab, editor chrome) are never compiled in. `.fixed` may exist while
`.bottom-6` / `.right-6` / `z-[9999]` do not → a `position: fixed` element
with no offsets keeps its in-flow position (spec) and lands thousands of px
below the viewport. Put new-component layout styles in the project's own
`globals.css`:

```css
/* src/app/globals.css */
.studio-fab {
  position: fixed; bottom: 24px; right: 24px; z-index: 9999;
  display: inline-flex; align-items: center; gap: 8px;
  padding: 12px 20px; border-radius: 9999px; color: #fff;
  background: #1B4D3E; text-decoration: none; cursor: pointer;
}
```

Verify visibility with the rect: `getBoundingClientRect()` must sit inside
the viewport (e.g. y ≈ 836 for a 900px-tall viewport), not ~6000px below.
(The original bug was exactly this: button present in the DOM,
`computed position: fixed`, `z-index: auto`, rect.y = 6176.)

## Drift-check method (proves fidelity before shipping)

After wiring, assert the merged (UCD-over-module) output equals the module-only
output for **every** `t()` key the public components call:

1. Extract keys: scan clone components for `t("key")`.
2. Build the two resolvers: `moduleOnly(key)` and `merged(key)` (merge policy).
3. For each key, assert `merged(key) === moduleOnly(key)`. If all equal, loading
   the UCD changes zero visible text — the public site is 100% faithful until an
   edit is made.

In the proven build this passed for all 73 sampled keys. The check also reveals
whether the seed is faithful (if any key drifts, the seed data is wrong, not the
adapter).

## Verification checklist

- [ ] `npx tsc --noEmit` clean; `eslint` clean.
- [ ] All public routes + `/studio` return 200.
- [ ] Home renders the faithful original copy (e.g. exact hero string).
- [ ] A `POST /api/studio/patch` edit (e.g. `nav.home`) is reflected by
      `GET /api/studio/document`.
- [ ] **Restart `npm run dev`** → the edit survives (seed skipped regeneration).
- [ ] Revert the test edit to the faithful baseline.
- [ ] Drift check: 0 differences across all sampled `t()` keys.
- [ ] DOM-injected baseline: the edited value appears on the **public page**
      without a rebuild (needs `force-dynamic` + mtime-validated cache; verifies
      the Next 16 cross-instance fix).
- [ ] DOM-injected baseline: no-edit output is byte-identical to the original
      page (placeholder substitution is lossless).
- [ ] DOM-injected baseline + InteractiveTier: an **unedited** page mounts the
      bundle and its interactivity works (e.g. FAQ accordion toggles); after
      editing that page's slug, the bundle disappears and the edit renders,
      while other unedited pages keep their bundle.
