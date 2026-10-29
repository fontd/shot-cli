"""Check what shot exists for: the page really sees a phone, in both engines. Run: python3 test_shot.py"""
import pathlib
import tempfile
from playwright.sync_api import sync_playwright

import shot

PAGE = '<meta name=viewport content="width=device-width"><body style="height:3000px">phone?</body>'

with tempfile.TemporaryDirectory() as tmp:
    html = pathlib.Path(tmp, 'p.html')
    html.write_text(PAGE)
    with sync_playwright() as p:
        for name, launch in [('chromium', lambda: p.chromium.launch(channel='chrome')), ('webkit', p.webkit.launch)]:
            b = launch()
            opts = dict(p.devices['iPhone 13'])
            opts.pop('default_browser_type')
            page = b.new_context(**opts).new_page()
            page.goto(html.as_uri())
            seen = page.evaluate('[innerWidth, matchMedia("(max-width:500px)").matches, matchMedia("(pointer:coarse)").matches]')
            assert seen[0] == 390 and seen[1] and seen[2], (name, seen)
            b.close()
        for name in shot.SAMPLE:  # every sample size resolves to a viewport
            assert shot.device_opts(p.devices, name)['viewport']['width'] > 0, name
    # end to end: two URLs, two devices, webkit, full page with the scroll loop
    out = str(pathlib.Path(tmp, 'o.png'))
    shot.main([html.as_uri(), html.as_uri(), '-o', out, '-d', 'iPhone 13', '-d', 'desktop', '-e', 'webkit', '--full', '--wait', '0', '--hide', 'body'])
    from PIL import Image
    w = Image.open(pathlib.Path(tmp, 'o-iphone-13.png')).width
    assert w == 2 * 390 * 3 + 40, w
    assert pathlib.Path(tmp, 'o-desktop.png').exists()
    sheet = Image.open(out)  # contact sheet at CSS px: iPhone pair (2×390 + 40/3) and desktop 1440 side by side
    assert sheet.width > 1440 + 780 and sheet.height > 900, sheet.size
    # --dark reaches the page; --click runs before the capture
    btn = pathlib.Path(tmp, 'b.html')
    btn.write_text('<style>body{margin:0;background:#fff}@media (prefers-color-scheme:dark){body{background:#000}}</style>'
                   '<button onclick="document.body.style.background=\'rgb(255,0,0)\'">go</button>')
    for extra, colour in [(['--dark'], (0, 0, 0)), (['--light', '--click', 'button'], (255, 0, 0))]:
        shot.main([btn.as_uri(), '-o', out, '--wait', '0', *extra])
        assert Image.open(out).convert('RGB').getpixel((600, 1500)) == colour, (extra, colour)
    # --check: every planted problem is reported on the phone, and a clean page reports nothing
    bad = pathlib.Path(tmp, 'bad.html')
    bad.write_text('<meta name=viewport content="width=device-width"><body style="margin:0">'
                   '<div style="width:600px">wide</div><button style="width:16px;height:16px">x</button>'
                   '<button style="width:16px;height:16px">y</button><br><br><button style="width:16px;height:16px">alone</button>'
                   '<div style="width:80px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">a very long title here</div>'
                   '<img src="missing.png" style="width:50px;height:50px">'
                   '<div style="position:fixed;bottom:0;left:0;right:0;height:60vh">cookies</div>'
                   '<script>undefinedFunction()</script>')
    good = pathlib.Path(tmp, 'good.html')
    good.write_text('<meta name=viewport content="width=device-width"><p>Hello</p><button style="padding:12px">Buy</button>')
    import contextlib, io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        n = shot.main([bad.as_uri(), good.as_uri(), '--check', '--wait', '0'])
    text = buf.getvalue()
    for needle in ('scrolls sideways', 'sticks out', 'tap target 16×16', 'text cut', 'broken image', 'fixed layer covers', 'JS error'):
        assert needle in text, (needle, text)
    assert f'{good.as_uri()}: OK' in text, text
    assert '"alone"' not in text, text  # WCAG spacing exception: a small target with room around it passes
    assert n >= 7, n
    # devices in parallel processes (run as a program: worker processes re-import __main__), a page that does not
    # load is a finding, exit code 1
    import subprocess, sys
    r = subprocess.run([sys.executable, str(pathlib.Path(shot.__file__)), bad.as_uri(), good.as_uri(), 'http://127.0.0.1:9/',
                        '--check', '-d', 'iPhone 13', '-d', 'desktop', '--wait', '0'], capture_output=True, text=True)
    assert r.returncode == 1, r
    assert 'did not load' in r.stdout and f'{good.as_uri()}: OK' in r.stdout, r.stdout
    assert 'scrolls sideways' in r.stdout and 'on iPhone 13 · 390 px' in r.stdout, r.stdout
    # what all pages share is listed once, first
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        shot.main([bad.as_uri() + f'?{i}' for i in range(3)] + ['--check', '--wait', '0'])
    text = buf.getvalue()
    assert text.startswith('On every page (3)') and text.count('broken image') == 1 and f'{bad.as_uri()}?2: OK' in text, text
    # --json + --html (crops), then --baseline: the same run again has nothing new; a problem missing from the
    # baseline comes back as new
    import json
    j, h = pathlib.Path(tmp, 'r.json'), pathlib.Path(tmp, 'r.html')
    with contextlib.redirect_stdout(io.StringIO()):
        first = shot.main([bad.as_uri(), good.as_uri(), '--check', '--wait', '0', '--json', str(j), '--html', str(h)])
        assert shot.main([bad.as_uri(), good.as_uri(), '--check', '--wait', '0', '--baseline', str(j)]) == 0
    page = h.read_text()
    assert page.count('<li>') == first and 'data:image/png;base64,' in page and 'tap target 16×16' in page, page[:500]
    base = json.loads(j.read_text())
    cut = next(p for p in base['pages'][bad.as_uri()] if p.startswith('broken image'))
    del base['pages'][bad.as_uri()][cut]
    j.write_text(json.dumps(base))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert shot.main([bad.as_uri(), good.as_uri(), '--check', '--wait', '0', '--baseline', str(j)]) == 1
    assert cut in buf.getvalue() and 'JS error' not in buf.getvalue(), buf.getvalue()
    # --sitemap: products in two chunks (with image entries) count as one kind, the /es/ copy is skipped (it is not
    # even served: fetching it would fail), 2 pages spread through each kind, plus the URL given
    import functools, http.server, threading
    site = pathlib.Path(tmp, 'site')
    site.mkdir()
    ns = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:image="http://www.google.com/schemas/sitemap-image/1.1"'
    (site / 'sitemap.xml').write_text(f'<sitemapindex {ns}>' + ''.join(
        f'<sitemap><loc>http://127.0.0.1:{{port}}/{s}</loc></sitemap>'
        for s in ('sitemap_a_1.xml?from=1&amp;to=5', 'sitemap_a_2.xml', 'es/sitemap_a_1.xml', 'sitemap_b_1.xml')) + '</sitemapindex>')
    for name, first in (('a_1', 0), ('a_2', 5), ('b_1', 0)):
        (site / f'sitemap_{name}.xml').write_text(f'<urlset {ns}>' + ''.join(
            f'<url><loc>http://x/{name[0]}{i}</loc><image:image><image:loc>http://x/img{i}.jpg</image:loc></image:image></url>'
            for i in range(first, first + 5)) + ('<url><loc>http://x/agents.md</loc></url>' if name == 'b_1' else '') + '</urlset>')
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(http.server.SimpleHTTPRequestHandler, directory=site))
    port = server.server_address[1]
    (site / 'sitemap.xml').write_text((site / 'sitemap.xml').read_text().replace('{port}', str(port)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with sync_playwright() as p:
        pages = shot.sitemap_pages(p, f'http://127.0.0.1:{port}/', 2)
    server.shutdown()
    assert pages == [f'http://127.0.0.1:{port}/', 'http://x/a0', 'http://x/a5', 'http://x/b0', 'http://x/b2'], pages
print('ok')
