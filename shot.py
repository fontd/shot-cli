#!/usr/bin/env python3
"""Screenshot a page the way a real phone (or desktop) renders it.

Plain headless Chrome with --window-size won't go below ~500 px and ignores the meta viewport, so
"mobile" captures come out wrong. Playwright emulates the whole device: viewport, retina, touch,
user agent, isMobile.

  shot.py URL [URL2] [-o out.png] [-d "iPhone 13"] [-d desktop] [-e webkit] [--selector .hero] [--full]
          [--click "button.cart"] [--dark | --light] [--check]

-d sample = 15 sizes from iPhone SE to 1920 px, foldables included.
Two URLs = before/after, side by side in one image. Several -d = one file per device (out-<device>.png)
plus out.png, a contact sheet of them all at CSS-pixel scale, each labelled with its device and width.
-e chromium uses the installed Chrome (no download); -e webkit is Safari's engine (playwright install webkit).
"""
import argparse
import os
import re
import sys
from playwright.sync_api import Error as PlaywrightError, sync_playwright

DESKTOPS = {'laptop': (1280, 800), 'desktop': (1440, 900), 'wide': (1920, 1080)}
# Not in Playwright yet. iPhone Duo (foldable, 2026): Apple's panels are 1398×2034 (outer, 460 ppi) and 1878×2670
# (inner, 430 ppi); @3x is inferred (Apple uses 3x from ~400 ppi), giving 466×678 and 890×626, or 626×890 rotated.
CUSTOM = {'iPhone Duo': ('iPhone 15 Pro Max', 466, 678, 3), 'iPhone Duo open': ('iPhone 15 Pro Max', 890, 626, 3),
          'iPhone Duo open portrait': ('iPhone 15 Pro Max', 626, 890, 3)}
# -d sample: small, common and big phones, foldables (folded and open), tablet both ways, three desktop widths
SAMPLE = ['iPhone SE', 'iPhone 13', 'iPhone 15 Pro Max', 'iPhone Duo', 'iPhone Duo open', 'iPhone Duo open portrait', 'Galaxy S24', 'Galaxy A55',
          'Galaxy Z Fold 7 Cover', 'Galaxy Z Fold 7', 'iPad Mini', 'iPad Mini landscape', 'laptop', 'desktop', 'wide']

HIDE_JS = '''(css) => document.addEventListener('DOMContentLoaded', () => {
  const s = document.createElement('style');
  s.textContent = css;
  document.head.appendChild(s);
})'''


def device_opts(devices, name):
    if name in DESKTOPS:
        w, h = DESKTOPS[name]
        return {'viewport': {'width': w, 'height': h}}
    if name in CUSTOM:
        base, w, h, dpr = CUSTOM[name]
        opts = dict(devices[base], viewport={'width': w, 'height': h}, screen={'width': w, 'height': h}, device_scale_factor=dpr)
    else:
        opts = dict(devices[name])
    opts.pop('default_browser_type', None)
    return opts


def load(page, url, a, scroll):
    page.goto(url, wait_until='load', timeout=60000)
    if scroll:  # scroll through so lazy sections (IntersectionObserver) load
        try:
            h = page.evaluate('document.body.scrollHeight')
            for _ in range(0, h, 600):
                page.evaluate('window.scrollBy(0, 600)')  # mouse.wheel isn't supported in mobile WebKit
                page.wait_for_timeout(120)
            page.evaluate('window.scrollTo(0, 0)')
        except PlaywrightError:  # the site reloaded itself (consent, geo redirect): take it from the new page
            page.wait_for_load_state('load')
    for sel in a.click:  # open a cart, menu or drawer first; the state after the last click is captured
        page.locator(sel).first.click()
        page.wait_for_timeout(600)
    page.wait_for_timeout(a.wait)


# What --check looks for, from inside the page. Text, not pixels: cheap to read and nothing slips past a glance.
CHECK_JS = '''(vw) => {
  // vw is the device's width: a phone zooms out to fit a page that is too wide, so innerWidth grows with it.
  const out = [], all = [...document.querySelectorAll('body *')];
  const desc = e => {
    let s = e.tagName.toLowerCase();
    if (e.id) s += '#' + e.id; else if (e.classList.length) s += '.' + [...e.classList].slice(0, 2).join('.');
    const t = (e.innerText || e.alt || e.getAttribute('aria-label') || '').trim().replace(/\\s+/g, ' ').slice(0, 40);
    return t ? `${s} "${t}"` : s;
  };
  const shown = e => {
    const c = getComputedStyle(e), r = e.getBoundingClientRect();
    // over 2 px: skip links and screen-reader text are 1×1 on purpose
    return c.display !== 'none' && c.visibility !== 'hidden' && +c.opacity > 0 && r.width > 2 && r.height > 2;
  };
  const sw = document.documentElement.scrollWidth;
  if (sw > vw + 1) out.push(`scrolls sideways: page is ${sw} px on a ${vw} px screen`);
  // Partly off the right edge (wholly off-screen = a closed drawer, on purpose) and not clipped by a scroller.
  const free = e => { for (let p = e.parentElement; p && p !== document.body; p = p.parentElement)
    if (getComputedStyle(p).overflowX !== 'visible') return false; return true; };
  const wide = all.filter(e => { const r = e.getBoundingClientRect(); return r.left < vw && r.right > vw + 1 && shown(e) && free(e); });
  wide.filter(e => !wide.includes(e.parentElement)).slice(0, 8)
    .forEach(e => out.push(`sticks out ${Math.round(e.getBoundingClientRect().right - vw)} px on the right: ${desc(e)}`));
  if (matchMedia('(pointer: coarse)').matches) {
    // WCAG 2.5.8: under 24 px fails unless a 24 px square centred on it touches no other target (spacing exception);
    // links inside running text are exempt too.
    const targets = [...document.querySelectorAll('a[href], button, input:not([type=hidden]), select, textarea, [role=button]')]
      .filter(shown).map(e => [e, e.getBoundingClientRect()]);
    const crowded = (e, r) => { const cx = (r.left + r.right) / 2, cy = (r.top + r.bottom) / 2;
      return targets.some(([o, q]) => o !== e && !o.contains(e) && !e.contains(o)
        && q.left < cx + 12 && q.right > cx - 12 && q.top < cy + 12 && q.bottom > cy - 12); };
    const small = targets.filter(([e, r]) => (r.width < 24 || r.height < 24) && crowded(e, r)
      && !(getComputedStyle(e).display === 'inline' && e.closest('p, li, td'))).map(([e]) => e);
    small.slice(0, 8).forEach(e => { const r = e.getBoundingClientRect();
      out.push(`tap target ${Math.round(r.width)}×${Math.round(r.height)} px (under 24): ${desc(e)}`); });
    if (small.length > 8) out.push(`… and ${small.length - 8} more small tap targets`);
  }
  all.filter(e => { const c = getComputedStyle(e);  // under 20 px wide = an icon or dot whose label is hidden on purpose
    return shown(e) && e.getBoundingClientRect().width >= 20 && ((c.textOverflow === 'ellipsis' && e.scrollWidth > e.clientWidth + 1)
      || (c.webkitLineClamp && c.webkitLineClamp !== 'none' && e.scrollHeight > e.clientHeight + 1)); })
    .slice(0, 8).forEach(e => out.push(`text cut with …: ${desc(e)}`));
  [...document.images].filter(i => i.complete && i.naturalWidth === 0 && i.getAttribute('src') && shown(i))
    .slice(0, 8).forEach(i => out.push(`broken image: ${i.currentSrc || i.src}`));
  const fixed = all.filter(e => /fixed|sticky/.test(getComputedStyle(e).position) && shown(e));
  fixed.filter(e => !fixed.some(f => f !== e && f.contains(e))).forEach(e => {
    const r = e.getBoundingClientRect();
    const w = innerWidth, h = innerHeight;  // what is on screen now, zoomed out or not
    const area = Math.max(0, Math.min(r.right, w) - Math.max(r.left, 0)) * Math.max(0, Math.min(r.bottom, h) - Math.max(r.top, 0));
    // in quarters, so one banner reads as one problem across devices instead of 37 %, 39 %, 45 %…
    const q = Math.floor(4 * area / (w * h));
    if (q) out.push(`fixed layer covers over ${25 * q} % of the screen: ${desc(e)}`);
  });
  return out;
}'''


# Failing requests every visitor gets, by design of the platform: not the page's fault.
NOISE = ('/sf_private_access_tokens',)  # Shopify storefronts answer 401 to every anonymous visitor


def check(ctx, url, a):
    page = ctx.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(f'JS error: {str(e)[:160]}'))
    # «Failed to load resource» repeats what the response hook or the broken-image check already says
    page.on('console', lambda m: m.type == 'error' and not m.text.startswith('Failed to load resource')
            and errors.append(f'console error: {m.text[:160]}'))
    page.on('response', lambda r: r.status >= 400 and not any(n in r.url for n in NOISE)
            and errors.append(f'{r.status} {r.url[:160]}'))
    try:
        load(page, url, a, scroll=True)
        found = page.evaluate(CHECK_JS, page.viewport_size['width'])
    except PlaywrightError as e:  # a timeout or a crash is a finding for this page, not the end of the run
        found = [f'did not load: {str(e).splitlines()[0][:160]}']
    page.close()
    return found + list(dict.fromkeys(errors))


def launch(p, a):
    return p.webkit.launch() if a.engine == 'webkit' else p.chromium.launch(channel='chrome')


def context(p, b, dev, a):
    """A throwaway profile as `dev` (presets never touch a real browser), with the run's cookies, hidden
    selectors and colour scheme. Returns it with its options and its «device · width px» label."""
    opts = device_opts(p.devices, dev)
    if a.scheme:
        opts['color_scheme'] = a.scheme
    ctx = b.new_context(**opts)
    hosts = {u.split('/')[2] for u in a.urls if '://' in u and not u.startswith('file:')}
    ctx.add_cookies([{'name': n, 'value': v, 'domain': h, 'path': '/'}
                     for c in a.cookie for n, v in [c.split('=', 1)] for h in hosts])
    if a.hide:  # on every load: a style injected once is lost when a site reloads itself
        ctx.add_init_script(f'({HIDE_JS})({", ".join(a.hide)!r} + " {{ display: none !important; }}")')
    return ctx, opts, f'{dev} · {opts["viewport"]["width"]} px'


def check_device(a, dev):
    """Every URL on one device, in a browser of its own, so devices can run in parallel processes."""
    with sync_playwright() as p:
        b = launch(p, a)
        ctx, opts, label = context(p, b, dev, a)
        found = {u: list(dict.fromkeys(check(ctx, u, a))) for u in a.urls}  # two identical elements = one line
        b.close()
    return label, opts.get('has_touch', False), found


def sitemap_pages(p, url, n):
    """The URL plus n pages from each sitemap of its site. Picked evenly through each list, not the first n, so a
    shop's oldest products don't stand in for all of them."""
    import xml.etree.ElementTree as ET
    from urllib.parse import urlsplit
    req = p.request.new_context()

    def read(sitemap):
        r = req.get(sitemap, timeout=30000)
        if not r.ok:
            raise SystemExit(f'{sitemap}: HTTP {r.status}')
        root = ET.fromstring(r.body())
        # direct children only: image sitemaps nest <image:loc> inside <url>
        return root.tag.endswith('sitemapindex'), [e.text.strip() for e in root.findall('{*}*/{*}loc') if e.text]

    own = url.endswith('.xml')
    index, found = read(url if own else '{0.scheme}://{0.netloc}/sitemap.xml'.format(urlsplit(url)))
    groups = {'': found}
    if index:  # one group per kind: sitemap_products_1…3 are one list; /ca/sitemap_products_1 is the same template
        groups = {}
        for s in found:
            folder, name = urlsplit(s).path.rsplit('/', 1)
            kind = groups.setdefault(re.sub(r'_\d+$', '', name.removesuffix('.xml')), [folder, []])
            if kind[0] == folder:
                kind[1] += read(s)[1]
        groups = {k: v[1] for k, v in groups.items()}
    pages = [] if own else [url]
    for group in groups.values():
        pages += group[::max(1, len(group) // n)][:n]
    req.dispose()
    return pages


def capture(ctx, url, a, out):
    page = ctx.new_page()
    load(page, url, a, scroll=a.full or a.selector)
    if a.selector:
        el = page.locator(a.selector).first
        # fixed/sticky bars (headers, chat bubbles) would sit on top of the element once it's scrolled to
        el.evaluate('''t => document.querySelectorAll('body *').forEach(e => {
          if (!e.contains(t) && !t.contains(e) && /fixed|sticky/.test(getComputedStyle(e).position)) e.style.visibility = 'hidden';
        })''')
        el.scroll_into_view_if_needed()
        page.wait_for_timeout(800)
        el.screenshot(path=out)
    else:
        page.screenshot(path=out, full_page=a.full)
    page.close()


def side_by_side(paths, out, gap=40):
    from PIL import Image
    ims = [Image.open(p) for p in paths]
    canvas = Image.new('RGB', (sum(i.width for i in ims) + gap * (len(ims) - 1), max(i.height for i in ims)), 'white')
    x = 0
    for im in ims:
        canvas.paste(im, (x, 0))
        x += im.width + gap
    canvas.save(out)


def sheet(shots, out, max_w=2400, gap=40, pad=28):
    """Every capture at CSS-pixel scale (retina divided out, so a phone and a desktop compare by size), in rows
    no wider than max_w, each with its label underneath."""
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.load_default(size=22)
    ims = []
    for path, label, dpr in shots:
        im = Image.open(path).convert('RGB')
        ims.append((im.resize((round(im.width / dpr), round(im.height / dpr))), label))
    rows, row, w = [], [], 0
    for im, label in ims:
        if row and w + gap + im.width > max_w:
            rows.append(row)
            row, w = [], 0
        w += (gap if row else 0) + im.width
        row.append((im, label))
    rows.append(row)
    label_h = 40
    width = max(sum(i.width for i, _ in r) + gap * (len(r) - 1) for r in rows) + 2 * pad
    height = sum(max(i.height for i, _ in r) + label_h for r in rows) + gap * (len(rows) - 1) + 2 * pad
    canvas = Image.new('RGB', (width, height), (238, 238, 238))
    draw = ImageDraw.Draw(canvas)
    y = pad
    for r in rows:
        x = pad
        for im, label in r:
            canvas.paste(im, (x, y))
            draw.text((x, y + im.height + 8), label, fill=(40, 40, 40), font=font)
            x += im.width + gap
        y += max(i.height for i, _ in r) + label_h + gap
    canvas.save(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('urls', nargs='+', metavar='URL', help='one URL, or two for before/after')
    ap.add_argument('-o', '--out', default='shot.png')
    ap.add_argument('-d', '--device', action='append', help='Playwright device name, laptop/desktop/wide, "iPhone Duo[ open]", '
                    'or "sample" (15 sizes, see SAMPLE); repeatable (default iPhone 13)')
    ap.add_argument('-e', '--engine', choices=['chromium', 'webkit'], default='chromium')
    ap.add_argument('--selector', help='capture only this element')
    ap.add_argument('--full', action='store_true', help='full page')
    ap.add_argument('--wait', type=int, default=4000, help='ms after load (app JS, lazy rows)')
    ap.add_argument('--hide', action='append', default=[], help='CSS selector to hide (banners, preview bars); repeatable')
    ap.add_argument('--cookie', action='append', default=[], help='NAME=VALUE preset on each URL host (e.g. cookie consent); repeatable')
    ap.add_argument('--click', action='append', default=[], metavar='SELECTOR',
                    help='click this before capturing (cart, menu, drawer); repeatable, in order')
    scheme = ap.add_mutually_exclusive_group()
    scheme.add_argument('--dark', dest='scheme', action='store_const', const='dark', help='prefers-color-scheme: dark')
    scheme.add_argument('--light', dest='scheme', action='store_const', const='light', help='prefers-color-scheme: light')
    ap.add_argument('--check', action='store_true', help='no images: list layout problems per device for every URL '
                    '(sideways scroll, small tap targets, cut text, broken images, big fixed layers, JS and HTTP errors)')
    ap.add_argument('--sitemap', type=int, metavar='N', help='with --check: also check N pages from each sitemap of '
                    'the site (products, collections, pages…), spread out; a URL ending in .xml is read as the sitemap itself')
    ap.add_argument('--jobs', type=int, default=4, help='with --check: devices checked at once, one browser each (default 4)')
    a = ap.parse_args(argv)
    if a.sitemap and not a.check:
        ap.error('--sitemap goes with --check')
    devices = [d for dev in (a.device or ['iPhone 13']) for d in (SAMPLE if dev == 'sample' else [dev])]
    if a.check:
        if a.sitemap:
            with sync_playwright() as p:
                a.urls = list(dict.fromkeys(pg for u in a.urls for pg in sitemap_pages(p, u, a.sitemap)))
            print(f'{len(a.urls)} pages × {len(devices)} devices', file=sys.stderr)
        if min(a.jobs, len(devices)) > 1:
            from concurrent.futures import ProcessPoolExecutor
            with ProcessPoolExecutor(min(a.jobs, len(devices))) as ex:
                results = list(ex.map(check_device, [a] * len(devices), devices))
        else:
            results = [check_device(a, dev) for dev in devices]
        report = {}
        for label, _, found in results:
            for u, problems in found.items():
                for problem in problems:
                    report.setdefault(u, {}).setdefault(problem, []).append(label)
        return print_report(report, a.urls, [(label, touch) for label, touch, _ in results])
    stem = a.out[:-4] if a.out.endswith('.png') else a.out
    written, shots = [], []
    with sync_playwright() as p:
        b = launch(p, a)
        for dev in devices:
            ctx, opts, label = context(p, b, dev, a)
            out = a.out if len(devices) == 1 else f'{stem}-{re.sub(r"[^a-z0-9]+", "-", dev.lower()).strip("-")}.png'
            if len(a.urls) == 1:
                capture(ctx, a.urls[0], a, out)
            else:
                parts = [f'{out[:-4]}.{i}.png' for i in range(len(a.urls))]
                for u, part in zip(a.urls, parts):
                    capture(ctx, u, a, part)
                side_by_side(parts, out)
                for part in parts:
                    os.remove(part)
            ctx.close()
            written.append(out)
            shots.append((out, label, opts.get('device_scale_factor', 1)))
        b.close()
    if len(devices) > 1:
        sheet(shots, f'{stem}.png')
        written.append(f'{stem}.png')
    print('\n'.join(written))


def where(seen, labels):
    """Shortest true description of the devices a problem shows up on."""
    for name, base in (('every touch device', [lbl for lbl, t in labels if t]), ('every device', [lbl for lbl, _ in labels])):
        missing = [lbl for lbl in base if lbl not in seen]
        if len(base) > 1 and set(seen) <= set(base) and len(missing) <= len(seen) / 2:
            return name + (' but ' + ', '.join(missing) if missing else '')
    return ', '.join(seen)


def print_report(report, urls, labels):
    """One block per URL; a problem seen on several devices is listed once, with where it happens."""
    for u in urls:
        problems = report.get(u, {})
        print(f'{u}: {"OK" if not problems else f"{len(problems)} problem(s)"}')
        for problem, seen in sorted(problems.items(), key=lambda kv: -len(kv[1])):
            print(f'  - {problem}\n      on {where(seen, labels)}')
    return sum(len(v) for v in report.values())


if __name__ == '__main__':
    raise SystemExit(1 if main() else 0)
