# Site Studio Builder — ChatGPT Project Instructions

> Paste the content below into a ChatGPT **Project's "Project instructions"**
> box, or into a **Custom GPT's System instructions**. It instructs ChatGPT to
> add an additive, non-destructive in-browser visual editor (`/studio`) to an
> existing website while keeping the public pages faithful to the original.

---

Use these instructions to add an **additive, non-destructive in-browser visual
editor** (a "Studio", served at route `/studio`) on top of an existing website —
most usefully when the site is a clone of another site. The public pages keep
rendering exactly as before; `/studio` lets editors change text / images /
section data, and those edits persist and appear on the public pages after
reload.

This was proven on a `medkungfu.com` clone: the public pages stayed byte-for-byte
faithful to the original while a studio editing mode was layered on top.

## Hard constraint — clone fidelity

The public pages **MUST remain byte-for-byte faithful** to the original site.
Studio is the **only** addition. Never overwrite clone copy/layout with
editor-authored defaults. Enforce this with a merge adapter: the original
dictionaries are the **base**; Studio edits only **override** specific keys.

## Prerequisites

- Next.js (App Router) + React.
- **Node ≥ 24** (Next 16 needs it; a managed `node` v22 is too old — use the
  system Node 24 or `nvm use 24`).
- Decide the "faithful baseline": the original copy/dictionaries the public site
  renders.

## Workflow

**1. Extract a faithful baseline into modules.** Put site copy in
`src/lib/i18n/translations.ts` (en+zh) and `ru.ts` (ru), plus `seed-data.ts` for
structured section data (hero image, ctaLinks, statKeys…). Components read via
`t()` and `useSectionData(page, id, fallback)`, where `fallback` is the seed
constant (prevents hydration mismatch because the content doc is `null` on the
server).

**2. Build the content layer.** Create `scripts/seed-ucd.ts` that reads those
modules and writes `.content/`: `translations.json` (en/zh/ru),
`pages/{slug}.json` (section data), `navigation.json`, `meta.json`. **First-run
only** — if `translations.json` already exists, skip regeneration so Studio edits
survive restarts/builds. Wire it via `predev`/`prebuild` npm hooks (`"seed": "tsx
scripts/seed-ucd.ts"`). Add `.content/`, `versions/` to `.gitignore`.

**3. Runtime + compat adapter.** Add `content-runtime.ts` (a module singleton
holding the in-memory content doc) and `compat-adapter.ts` (`compatTranslate` that
**MERGES** the doc over the hardcoded baseline: `{...module, ...doc}`). Components
switch from importing `TRANSLATIONS` directly to `useContentRuntime().translate()`
/ `useSectionData()`. A partial doc can never break rendering.

**4. Reconnect to public pages.** Add `ContentBootstrap.tsx` and mount it in
`layout.tsx` inside the language provider, but `return` early when
`pathname.startsWith("/studio")` (so it doesn't clobber the editor's own document
instance).

**5. Studio editor.** Scaffold `/studio` (client) with Puck: a `PendingPreview` →
`IntentPreview` card showing the parsed intent/operations, an `NLCommandBar` for
natural-language input, and a `StudioFab` floating button (env-gated: show in dev
or when `NEXT_PUBLIC_SHOW_STUDIO_FAB === "true"`).

**6. NL command API.** Add `/api/agent/command` (dryRun + apply) backed by a
`rule-matcher`; persist via `/api/studio/patch` (RFC-6902 ops) →
`LocalContentStore`. **Carry `answer` / `templates` / `error` / `suggestions`
end-to-end** to the preview so "help" shows the command list and failures show
concrete formats.

**7. Verify.** Typecheck + lint; all public routes 200; home renders faithful
copy; a patch-API edit persists and **survives a dev restart**; drift check
(merged doc vs module) shows 0 differences.

## Critical pitfalls

- **Node version.** Use Node ≥ 24 explicitly.
- **Seed must be first-run-only.** Otherwise every restart/build wipes Studio
  edits. Guard on `translations.json` existence; tell users to delete `.content/`
  to reset to the faithful baseline.
- **Merge, don't replace.** `compatTranslate` must be `{...module, ...doc}`;
  replacing with the doc breaks any key the doc does not cover.
- **ContentBootstrap must skip `/studio`** or it clobbers the editor's own
  document instance.
- **Hydration.** SSR and first client render must be identical — pass the
  seed-data constant as the `useSectionData` fallback (the doc is `null` on the
  server).

## Reference

For the verified, copy-pasteable code patterns (runtime singleton, merge adapter,
bootstrap, seed guard, drift-check method) and the full natural-language command
subsystem (API contract, rule-matcher, end-to-end carry-through, known UI-bug
fixes), see the repository's `site-studio-builder/references/architecture.md`,
`site-studio-builder/references/puck-canvas.md` (the block-based Puck canvas for
DOM-injected clones, incl. image editing), and
`site-studio-builder/references/nl-command-bar.md`.
