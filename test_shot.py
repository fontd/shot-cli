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
print('ok')
