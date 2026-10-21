#!/usr/bin/env python3
"""Pull new BabyLoveGrowth articles and open one pull request per article.

Runs from .github/workflows/babylovegrowth.yml. Nothing goes live until a
person reviews the pull request and merges it.

For each article not yet on the site (and with no earlier pull request,
open, merged or closed), it:
  1. builds <slug>.html in the site's article layout (scripts/blg_template.html)
  2. downloads the article's images into img/blog/ (the site's security
     policy only allows images served from mymegahealth.com)
  3. commits on branch blg/<slug> and opens a pull request

After a pull request is merged, `--index` (run by .github/workflows/blg-index.yml
on every push to main) adds the article to blog.html, the blog schema,
sitemap.xml and llms.txt. Keeping those edits out of the pull requests means
several pending articles never conflict with each other.

Local test without the API:  python3 scripts/babylovegrowth_sync.py --fixture article.json --no-git
"""
import argparse, datetime, html, json, os, re, subprocess, sys, urllib.parse, urllib.request

API = "https://api.babylovegrowth.ai/api/integrations/v1"
SITE = "https://mymegahealth.com/"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(ROOT, "scripts", "blg_template.html")
MAX_NEW_PER_RUN = 5
UA = "mymegahealth-sync/1.0"

# Blog categories (data-cat on blog.html) and the label shown on the article.
CATEGORY_RULES = [
    ("vaccines", "Vaccinations", r"vaccin|flu shot|shingles|shingrix|rsv|pneumon|tdap|covid shot|immuniz"),
    ("insurance", "Insurance", r"medicare|medicaid|insurance|part d|copay|otc card|otc benefit|formulary|prior auth|deductible|caremark|express scripts|optumrx"),
    ("switching", "Switching pharmacies", r"transfer|switch(ing)? pharmac|independent pharmac|chain pharmac"),
    ("medications", "Medications", r"refill|medication|prescription|glp-?1|ozempic|wegovy|mounjaro|zepbound|insulin|drug"),
    ("our-pharmacy", "Free delivery", r"deliver"),
    ("services", "Services", r"notary|money order|dmv|medical suppl"),
]
DEFAULT_CAT = ("health", "Health tips")

ALLOWED_TAGS = {"p", "h2", "h3", "h4", "ul", "ol", "li", "strong", "b", "em", "i", "a", "blockquote",
                "table", "thead", "tbody", "tr", "th", "td", "img", "figure", "figcaption", "br", "hr",
                "code", "pre", "sup", "sub"}
ALLOWED_ATTRS = {"a": {"href", "title"}, "img": {"src", "alt", "width", "height"},
                 "th": {"scope", "colspan", "rowspan"}, "td": {"colspan", "rowspan"}}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def api_get(path, key):
    req = urllib.request.Request(API + path, headers={"X-API-Key": key, "Content-Type": "application/json",
                                                       "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def unwrap(data, *keys):
    """The API docs don't pin the envelope; accept a bare value or common wrappers."""
    for k in keys:
        if isinstance(data, dict) and k in data:
            return data[k]
    return data


def list_articles(key):
    out, offset = [], 0
    while True:
        page = unwrap(api_get(f"/articles?limit=50&offset={offset}", key), "data", "articles", "items", "results")
        if not isinstance(page, list) or not page:
            break
        out.extend(page)
        if len(page) < 50:
            break
        offset += 50
    return out


def get_article(aid, key):
    return unwrap(api_get(f"/articles/{urllib.parse.quote(str(aid))}", key), "data", "article")


def run(cmd, check=True, capture=False):
    log("$", " ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT, check=check, text=True,
                          stdout=subprocess.PIPE if capture else None)


def clean_slug(slug, title):
    s = (slug or title or "").strip().lower().rsplit("/", 1)[-1]
    s = re.sub(r"\.html?$", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:90] or "article"


def pr_exists(branch):
    """True if any pull request (open, closed or merged) ever used this branch."""
    r = run(["gh", "pr", "list", "--state", "all", "--head", branch, "--json", "number", "--limit", "1"],
            check=False, capture=True)
    try:
        return bool(json.loads(r.stdout or "[]"))
    except json.JSONDecodeError:
        return True  # be safe: don't duplicate


def sanitize(fragment):
    import nh3
    attrs = {t: set(v) for t, v in ALLOWED_ATTRS.items()}
    return nh3.clean(fragment, tags=ALLOWED_TAGS, attributes=attrs, url_schemes={"http", "https", "mailto", "tel"},
                     link_rel=None, strip_comments=True)


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        data = r.read(8_000_001)
    if len(data) > 8_000_000:
        raise ValueError("image over 8 MB")
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif",
           "image/avif": ".avif"}.get(ctype)
    if not ext:
        raise ValueError(f"not an image ({ctype})")
    with open(dest + ext, "wb") as f:
        f.write(data)
    return dest + ext


def localize_images(body, slug, hero_url, created):
    """Copy images into img/blog/ and point the page at the local copies."""
    os.makedirs(os.path.join(ROOT, "img", "blog"), exist_ok=True)
    n = [0]

    def fetch(url):
        n[0] += 1
        path = download(url, os.path.join(ROOT, "img", "blog", f"{slug}-{n[0]}"))
        created.append(os.path.relpath(path, ROOT))
        return os.path.relpath(path, ROOT).replace(os.sep, "/")

    def repl(m):
        tag = m.group(0)
        src = re.search(r'src="([^"]+)"', tag)
        if not src or not src.group(1).startswith("http"):
            return tag
        try:
            local = fetch(html.unescape(src.group(1)))
        except Exception as e:  # drop images we can't copy rather than ship broken ones
            log("  image skipped:", src.group(1), e)
            return ""
        tag = tag.replace(src.group(0), f'src="{local}"')
        if "loading=" not in tag:
            tag = tag.replace("<img", '<img loading="lazy" decoding="async"', 1)
        return tag

    body = re.sub(r"<img\b[^>]*>", repl, body)
    hero = None
    if hero_url:
        try:
            hero = fetch(hero_url)
        except Exception as e:
            log("  hero image skipped:", e)
    return body, hero


def pick_category(art):
    text = " ".join(str(art.get(k) or "") for k in ("title", "seedKeyword", "meta_description")).lower()
    kws = art.get("keywords")
    if isinstance(kws, list):
        text += " " + " ".join(map(str, kws)).lower()
    for cat, label, pat in CATEGORY_RULES:
        if re.search(pat, text):
            return cat, label
    return DEFAULT_CAT


def plain(h):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h or ""))).strip()


def render(art, slug, today):
    title = plain(art.get("title")) or slug.replace("-", " ").title()
    desc = plain(art.get("meta_description") or art.get("excerpt"))[:300]
    raw = art.get("content_html") or ""
    if not raw and art.get("content_markdown"):
        import markdown
        raw = markdown.markdown(art["content_markdown"], extensions=["tables"])
    body = sanitize(raw)
    # the page already shows the title as its H1
    body = re.sub(r"^\s*<h1\b[^>]*>.*?</h1>\s*", "", body, count=1, flags=re.S | re.I)
    body = re.sub(r"<(/?)h1\b", r"<\1h2", body, flags=re.I)
    body = re.sub(r"<table\b", '<div class="tbl"><table', body, flags=re.I)
    body = re.sub(r"</table>", "</table></div>", body, flags=re.I)
    body = re.sub(r'<a href="(https?://(?!mymegahealth\.com)[^"]+)"', r'<a href="\1" target="_blank" rel="noopener"', body)
    body = re.sub(r"<p>", '<p class="stand">', body, count=1)
    words = len(plain(body).split())
    if words < 150:
        raise ValueError(f"only {words} words of content; skipping")
    cat, label = pick_category(art)
    return title, desc, body, words, cat, label


def related(cat, slug):
    blog = open(os.path.join(ROOT, "blog.html"), encoding="utf-8").read()
    cards = re.findall(r'<a class="card" data-cat="([^"]+)" href="([^"]+)">.*?<h2>(.*?)</h2>', blog, re.S)
    picks = [(h, t) for c, h, t in cards if c == cat and h != f"{slug}.html"][:3]
    if len(picks) < 3:
        picks += [(h, t) for c, h, t in cards if (h, t) not in picks and h != f"{slug}.html"][:3 - len(picks)]
    return "\n".join(f'        <a href="{h}">{t}</a>' for h, t in picks)


def pub_date(art, fallback):
    """The article's own publish date (publishedAt), falling back to today."""
    for k in ("publishedAt", "published_at", "created_at"):
        v = str(art.get(k) or "")[:10]
        try:
            datetime.date.fromisoformat(v)
            return v
        except ValueError:
            continue
    return fallback


def build_page(art, slug, today, created):
    today = pub_date(art, today)
    title, desc, body, words, cat, label = render(art, slug, today)
    body, hero = localize_images(body, slug, art.get("hero_image_url"), created)
    if hero:
        body = (f'<img src="{hero}" alt="{html.escape(title, quote=True)}" decoding="async" '
                f'style="border-radius:16px;margin:0 0 28px;width:100%">\n') + body
    url = SITE + slug + ".html"
    mins = max(1, round(words / 230))
    d = datetime.date.fromisoformat(today)
    ld = {"@context": "https://schema.org", "@type": "BlogPosting", "headline": title, "description": desc,
          "datePublished": today, "dateModified": today, "wordCount": words, "inLanguage": "en-US",
          "author": {"@type": "Organization", "name": "Mega Health Rx Pharmacy"},
          "publisher": {"@type": "Pharmacy", "name": "Mega Health Rx Pharmacy", "@id": SITE + "#pharmacy"},
          "mainEntityOfPage": {"@type": "WebPage", "@id": url}}
    if hero:
        ld["image"] = SITE + hero
    blocks = [ld, {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "Home", "item": SITE},
        {"@type": "ListItem", "position": 2, "name": "Blog", "item": SITE + "blog.html"},
        {"@type": "ListItem", "position": 3, "name": title, "item": url}]}]
    faq = art.get("faqJsonLd")
    if isinstance(faq, str):
        try:
            faq = json.loads(faq)
        except json.JSONDecodeError:
            faq = None
    if isinstance(faq, dict) and faq.get("@type") == "FAQPage" and faq.get("mainEntity"):
        blocks.append(faq)
    jsonld = "\n".join('<script type="application/ld+json">\n' + json.dumps(b, indent=2, ensure_ascii=False)
                       .replace("</", "<\\/") + "\n</script>" for b in blocks)
    page = open(TEMPLATE, encoding="utf-8").read()
    esc = lambda s: html.escape(s, quote=True)
    tab = title if len(title) > 48 else f"{title} | Mega Health Rx"
    rep = {"{{TITLE}}": esc(tab), "{{DESC}}": esc(desc), "{{URL}}": url, "{{H1}}": esc(title),
           "{{CHIP}}": esc(label), "{{DATE_ISO}}": today, "{{DATE_HUMAN}}": f"{d:%B} {d.day}, {d.year}",
           "{{READ}}": str(mins), "{{BODY}}": body, "{{JSONLD}}": jsonld, "{{MORE}}": related(cat, slug)}
    for k, v in rep.items():
        page = page.replace(k, v)
    if hero:
        page = page.replace('content="https://mymegahealth.com/storefront.jpg"', f'content="{SITE + hero}"')
    meta = {"id": art.get("id"), "slug": slug, "title": title, "desc": desc, "cat": cat, "label": label,
            "mins": mins, "date": today}
    page = page.replace("<head>", "<head>\n<!-- blg " + json.dumps(meta, ensure_ascii=False).replace("--", "\\u002d\\u002d") + " -->", 1)
    assert "{{" not in page
    with open(os.path.join(ROOT, slug + ".html"), "w", encoding="utf-8") as f:
        f.write(page)
    created.append(slug + ".html")
    return title, desc, cat, label, mins, url


def update_indexes(slug, title, desc, cat, label, mins, url, today):
    d = datetime.date.fromisoformat(today)
    # blog.html: card at the top of the list + Blog schema entry
    p = os.path.join(ROOT, "blog.html")
    b = open(p, encoding="utf-8").read()
    card = f'''      <a class="card" data-cat="{cat}" href="{slug}.html">
        <div class="meta">
          <span class="chip">{html.escape(label)}</span>
          <time datetime="{today}">{d:%B} {d.day}, {d.year}</time>
          <span class="read">{mins} min read</span>
        </div>
        <h2>{html.escape(title)}</h2>
        <p>{html.escape(desc)}</p>
        <span class="more">Read the article &rarr;</span>
      </a>
'''
    i = b.index('      <a class="card" data-cat=')
    b = b[:i] + card + b[i:]
    for raw in re.findall(r'<script type="application/ld\+json">(.*?)</script>', b, re.S):
        o = json.loads(raw)
        if o.get("@type") == "Blog":
            o["blogPost"].insert(0, {"@type": "BlogPosting", "headline": title, "url": url, "datePublished": today})
            b = b.replace(raw, "\n" + json.dumps(o, indent=2, ensure_ascii=False) + "\n")
    open(p, "w", encoding="utf-8").write(b)
    # sitemap
    p = os.path.join(ROOT, "sitemap.xml")
    s = open(p, encoding="utf-8").read()
    s = re.sub(r"(<loc>https://mymegahealth.com/blog.html</loc>\s*<lastmod>)[^<]*", r"\g<1>" + today, s)
    s = s.replace("</urlset>", f"  <url>\n    <loc>{url}</loc>\n    <lastmod>{today}</lastmod>\n"
                               f"    <changefreq>monthly</changefreq>\n    <priority>0.7</priority>\n  </url>\n</urlset>")
    open(p, "w", encoding="utf-8").write(s)
    # llms.txt
    p = os.path.join(ROOT, "llms.txt")
    l = open(p, encoding="utf-8").read()
    if "\n## Latest articles\n" not in l:
        l = l.rstrip("\n") + "\n\n## Latest articles\n\n"
    head, tail = l.split("\n## Latest articles\n\n", 1)
    l = head + "\n## Latest articles\n\n" + f"- [{title}]({url})\n" + tail
    open(p, "w", encoding="utf-8").write(l)


PR_BODY = """New article from BabyLoveGrowth: **{title}**

Preview the page: open **Files changed**, then `{slug}.html` → "View file".

**Before you merge, please check:**
- [ ] Medical facts, dosing, vaccine ages and insurance rules are correct
- [ ] Nothing promises what we don't offer (delivery times, prices, coverage, services)
- [ ] No claims we can't back up ("best", "guaranteed", "cheapest")
- [ ] The category on the blog page fits (currently **{label}**)

Merge to publish it on mymegahealth.com. Close without merging to reject it; it won't be imported again.

---
Seed keyword: {seed}
BabyLoveGrowth article id: {aid}
"""


def index_merged():
    """Add merged imported articles to blog.html, sitemap.xml and llms.txt. Returns the number added."""
    blog = open(os.path.join(ROOT, "blog.html"), encoding="utf-8").read()
    pending = []
    for name in os.listdir(ROOT):
        if not name.endswith(".html"):
            continue
        head = open(os.path.join(ROOT, name), encoding="utf-8").read(4000)
        m = re.search(r"<!-- blg (\{.*?\}) -->", head)
        if m and f'href="{name}"' not in blog:
            pending.append((name, json.loads(m.group(1))))
    # oldest first, so the newest article ends up at the top of the blog list
    pending.sort(key=lambda x: (x[1].get("date", ""), x[0]))
    added = 0
    for name, meta in pending:
        update_indexes(meta["slug"], meta["title"], meta["desc"], meta["cat"], meta["label"], meta["mins"],
                       SITE + name, meta["date"])
        blog = open(os.path.join(ROOT, "blog.html"), encoding="utf-8").read()
        log(f"indexed {name}")
        added += 1
    return added


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", help="path to an article JSON (skips the API)")
    ap.add_argument("--no-git", action="store_true", help="write files only; no branches or pull requests")
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    ap.add_argument("--index", action="store_true", help="add merged articles to blog.html, sitemap and llms.txt")
    args = ap.parse_args()

    if args.index:
        log(f"done: {index_merged()} article(s) added to the blog index")
        return

    if args.fixture:
        arts = [json.load(open(args.fixture, encoding="utf-8"))]
        key = None
    else:
        key = os.environ.get("BABYLOVEGROWTH_API_KEY")
        if not key:
            sys.exit("BABYLOVEGROWTH_API_KEY is not set. Add it under Settings -> Secrets and variables -> Actions.")
        arts = list_articles(key)
        log(f"{len(arts)} articles in BabyLoveGrowth")

    made = 0
    for summary in arts:
        if made >= MAX_NEW_PER_RUN:
            log("reached the per-run limit; the rest will come on the next run")
            break
        lang = str(summary.get("languageCode") or "en").lower()
        if not lang.startswith("en"):
            continue  # the site is English-only
        slug = clean_slug(summary.get("slug"), summary.get("title"))
        branch = f"blg/{slug}"
        if os.path.exists(os.path.join(ROOT, slug + ".html")):
            continue
        if not args.no_git and pr_exists(branch):
            continue
        log(f"new article: {slug}")
        art = summary if args.fixture else get_article(summary["id"], key)
        if not args.no_git:
            run(["git", "checkout", "-B", branch, "origin/main"])
        created = []
        try:
            title, desc, cat, label, mins, url = build_page(art, slug, args.date, created)
        except Exception as e:
            log(f"  skipped {slug}: {e}")
            for f in created:
                try:
                    os.remove(os.path.join(ROOT, f))
                except OSError:
                    pass
            if not args.no_git:
                run(["git", "checkout", "--", "."], check=False)
                run(["git", "checkout", "main"], check=False)
            continue
        if args.no_git:
            log(f"  wrote {slug}.html")
            made += 1
            continue
        run(["git", "add", "-A"])
        run(["git", "commit", "-m", f"New article: {title}\n\nImported from BabyLoveGrowth (id {art.get('id')})."])
        run(["git", "push", "-f", "origin", branch])
        body = PR_BODY.format(title=title, slug=slug, label=label, seed=art.get("seedKeyword") or "-",
                              aid=art.get("id"))
        run(["gh", "pr", "create", "--base", "main", "--head", branch, "--title", f"New article: {title}",
             "--body", body])
        run(["git", "checkout", "main"])
        made += 1
    log(f"done: {made} new article(s)")


if __name__ == "__main__":
    main()
