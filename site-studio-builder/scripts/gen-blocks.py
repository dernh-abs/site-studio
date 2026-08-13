"""gen-blocks.py — split each DOM-injected page into editable blocks for the
Puck canvas, and emit `public/studio-blocks/{slug}.json`.

WHY THIS EXISTS
  A DOM-injected clone has no React component tree, so a Puck canvas has
  nothing to render by default. This script recovers a *page-level* tree from
  the injected HTML: it walks each page's HTML string, splits it on natural
  container boundaries (<main>, <section>, <header role="banner">), and emits
  one "block" per split unit. Each block carries:

    { id, title, html, keys: [text keys whose baseline appears inside], images: [{key, url}] }

  The Puck editor then registers ONE generic PageBlock component per block
  (see references/puck-canvas.md) and renders each block's HTML with
  dangerouslySetInnerHTML, substituting edited values back in. This turns a
  flat injected HTML page into a structured, selectable-outline canvas.

LAYOUT ASSUMPTION (medkungfu.com, generalizes to most DOM-injection clones)
  The injected HTML is a single `<div id="root">` whose first child is the page
  shell `<div class="flex flex-col ...">` containing [header, main, footer].
  `main`'s direct children are the page sections. If your clone's shell
  differs, adjust `build_on_full()` — everything below it is generic.

OUTPUT
  public/studio-blocks/{slug}.json  ->  { "slug": slug, "blocks": [ ... ] }

REGENERATE ANY TIME the injected HTML changes. The blocks files are gitignored
in the host project (they are derived artifacts). Re-run after re-cloning or
after changing the page generator.
"""
import json
import re
from pathlib import Path

# ── Configure these for your clone ─────────────────────────────────────
# Where the generated page components live (each page.tsx wraps its injected
# HTML in applyOverrides(`<div id="root">...`, ...)).
ROOT = Path("src/app")
# Where block descriptors are written.
OUT = Path("public/studio-blocks")
# The faithful baseline text dict (flat dotted keys -> original text). This is
# the same file the seed step writes; the script only reads it to decide which
# keys live inside which block.
BASE = json.load(open(".content/translations.json", encoding="utf-8"))["en"]

# Tags that can begin a child block when splitting.
TAGS = ["header", "main", "footer", "section", "div", "nav", "aside", "article"]
# Tags that are recursively split into sub-blocks (everything else is one block).
SPLITTABLE = ("main", "section")
# Max recursion depth for splitting (keeps huge pages from over-fragmenting).
MAX_DEPTH = 4


def extract_html(page_tsx: str) -> str:
    """Pull the injected HTML string out of a page.tsx that calls
    applyOverrides(`<div id="root">...</div>`, ...). Adjust the regex if your
    generator emits a different wrapper. """
    m = re.search(r"applyOverrides\(`(<div id=\"root\">.*?)`,\s*'[^']+'\s*,", page_tsx, re.S)
    return m.group(1) if m else ""


def find_matching(html: str, start: int, tag: str) -> int:
    """Index just past the matching close tag of <tag> starting at `start`
    (start points AT the opening tag). Depth goes up on open, down on close;
    the close that brings depth to zero is the matching one. """
    depth = 0
    i = start
    open_re = re.compile(rf"<{tag}[\s>]")
    while i < len(html):
        if html.startswith(f"</{tag}", i):
            depth -= 1
            if depth <= 0:
                return i + len(f"</{tag}>")
            i += len(f"</{tag}>")
            continue
        if open_re.match(html, i):
            depth += 1
        i += 1
    return len(html)


def split_children(html: str, start: int, end: int):
    """Direct children inside html[start:end]; `start` must point AFTER the
    container's opening tag so the container itself is not matched. """
    children = []
    i = start
    while i < end:
        m = re.search(r"<(header|main|footer|section|div|nav|aside|article)[\s>]", html[i:end])
        if not m:
            break
        tag = m.group(1)
        s = i + m.start()
        e = find_matching(html, s, tag)
        children.append((tag, s, e))
        i = e
    return children


def tag_close(html: str, start: int) -> int:
    """Index just past the first '>' at/after `start` (opening tag end)."""
    return html.index(">", start) + 1


def slug_of(p: Path) -> str:
    """Derive the page slug from the file path. `src/app/page.tsx` → "index";
    `src/app/ru/about/page.tsx` → "ru__about". Must mirror the slug the seed
    step used when it generated the translation keys. """
    rel = p.relative_to(ROOT)
    return "index" if rel == Path("page.tsx") else "__".join(rel.parts[:-1])


def title_for(tag: str, seg: str) -> str:
    m = re.search(r'class="([^"]{0,60})', seg)
    cls = m.group(1) if m else ""
    return f"<{tag}> {cls}" if cls else f"<{tag}>"


def keys_in_seg(seg: str, slug: str) -> list[str]:
    """Every baseline text key (slug.*) whose original value appears verbatim
    inside this HTML segment. The value must be a non-empty substring match —
    this is what lets the editor substitute edited values back via
    `html.split(original).join(edited)`. """
    prefix = slug + "."
    keys = []
    for k, v in BASE.items():
        if not k.startswith(prefix):
            continue
        if v and v in seg:
            keys.append(k)
    return keys


IMG_SRC_RE = re.compile(r"<img[^>]*\bsrc\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
CSS_URL_RE = re.compile(r"url\(\s*['\"]?([^)'\"]+)['\"]?\s*\)", re.IGNORECASE)


def images_in_seg(seg: str, block_id: str, slug: str) -> list[dict]:
    """Extract editable image URLs (img src + CSS url()) from a block.
    data: URIs are skipped (too large). Keys are "<slug>__<blockId>__img<n>"
    and are the patch paths the Studio writes for image edits. """
    urls: list[str] = []
    for m in IMG_SRC_RE.finditer(seg):
        u = m.group(1).strip()
        if u.startswith("data:"):
            continue
        if u.startswith(("http://", "https://", "/")):
            urls.append(u)
    for m in CSS_URL_RE.finditer(seg):
        u = m.group(1).strip()
        if u.startswith("data:"):
            continue
        if u.startswith(("http://", "https://", "/")):
            urls.append(u)
    seen = set()
    imgs = []
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        imgs.append({"key": f"{slug}__{block_id}__img{len(imgs)}", "url": u})
    return imgs


def expand(blocks, html, s, e, slug, prefix, depth=0, max_depth=MAX_DEPTH):
    """Recursively split the container [s, e) into sub-blocks. A container is
    split if it has ≥2 direct children that are themselves split-worthy (a
    <main>, <section>, or <header role="banner">). Otherwise the whole segment
    is emitted as one block.

    Block-id naming: `main-0` (depth 0) → `main-0-0`, `main-0-1` (depth 1) →
    `main-0-0-0`, ... — keeps every leaf id unique.

    Single-child passthrough: when a container has exactly ONE split-worthy
    child (the common `<main><main>…</main></main>` nesting), descend through
    the wrapper instead of emitting an extra block — keeps ids stable.
    """
    if depth > max_depth:
        add_block(blocks, prefix, "main", html[s:e], slug)
        return
    mte = tag_close(html, s)
    subs = split_children(html, mte, e)
    keep = [
        (t, s2, e2)
        for (t, s2, e2) in subs
        if t in SPLITTABLE or (t == "header" and 'role="banner"' in html[s2:e2])
    ]
    if len(keep) >= 2:
        for i, (t, s2, e2) in enumerate(keep):
            child_id = f"{prefix}-{i}"
            expand(blocks, html, s2, e2, slug, child_id, depth + 1, max_depth)
    elif len(keep) == 1:
        (t, s2, e2) = keep[0]
        expand(blocks, html, s2, e2, slug, prefix, depth + 1, max_depth)
    else:
        add_block(blocks, prefix, "main", html[s:e], slug)


def build_on_full(html: str, slug: str):
    """Split the full page HTML into blocks. Assumes the shell is
    `<div id="root"><div class="flex flex-col ...">[header, main, footer]`.
    Adjust this function if your clone's shell differs. """
    root_open = html.index("<div id=\"root\">") + len('<div id="root">')
    root_end = find_matching(html, 0, "div")
    flex_m = re.search(r"<div class=\"flex flex-col[^\"]*\"[\s>]", html[root_open:root_end])
    if not flex_m:
        return []
    fs = root_open + flex_m.start()
    fe = find_matching(html, fs, "div")
    fte = tag_close(html, fs)
    kids = split_children(html, fte, fe)
    blocks = []
    for (tag, s, e) in kids:
        if tag == "main":
            expand(blocks, html, s, e, slug, "main-0", 0)
        else:
            add_block(blocks, tag, tag, html[s:e], slug)
    return blocks


def add_block(blocks, bid, tag, seg, slug):
    blocks.append({
        "id": bid,
        "title": title_for(tag, seg),
        "html": seg,
        "keys": keys_in_seg(seg, slug),
        "images": images_in_seg(seg, bid, slug),
    })


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    total_blocks = 0
    total_keys = 0
    for p in sorted(ROOT.rglob("page.tsx")):
        if "studio" in p.parts:  # never treat the /studio pages as editable content
            continue
        slug = slug_of(p)
        html = extract_html(p.read_text(encoding="utf-8"))
        if not html:
            print(f"SKIP (no html) {slug}")
            continue
        blocks = build_on_full(html, slug)
        if not blocks:
            print(f"NO BLOCKS {slug}")
            continue
        (OUT / f"{slug}.json").write_text(
            json.dumps({"slug": slug, "blocks": blocks}, ensure_ascii=False),
            encoding="utf-8",
        )
        nk = sum(len(b["keys"]) for b in blocks)
        total_blocks += len(blocks)
        total_keys += nk
        print(f"{slug}: {len(blocks)} blocks, {nk} keys")
    print("TOTAL:", total_blocks, "blocks,", total_keys, "keys")


if __name__ == "__main__":
    main()
