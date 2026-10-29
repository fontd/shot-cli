# shot

Screenshots of a page as a real phone renders it, from the command line.

Plain headless Chrome with `--window-size` won't go below ~500 px wide and ignores the meta viewport, so its "mobile" captures are wrong. `shot` uses Playwright's device emulation: viewport, retina, touch, mobile user agent.

## Install

```sh
pip install playwright pillow
python3 -m playwright install webkit   # only for -e webkit (Safari's engine, ~80 MB)
```

The default engine uses your installed Google Chrome, so nothing else is downloaded.

## Use

```sh
python3 shot.py https://example.com                       # iPhone 13, first screen → shot.png
python3 shot.py https://example.com -e webkit --full      # Safari engine, whole page
python3 shot.py URL -d "iPhone 13" -d "Pixel 7" -d desktop -o home.png   # home-iphone-13.png, home-pixel-7.png, home-desktop.png + home.png (sheet)
python3 shot.py BEFORE_URL AFTER_URL -o diff.png          # side by side
python3 shot.py URL -d sample -o s.png                     # 15 sizes: iPhone SE → 1920 px, foldables folded and open
python3 shot.py URL --selector .hero                      # one element (scrolls first so lazy content loads)
python3 shot.py URL --click '.cart-toggle' --click '.upsell'  # open the cart, then the upsell, then capture
python3 shot.py URL --dark                                 # prefers-color-scheme: dark (or --light)
```

With several devices, `out.png` is also a contact sheet: every capture at CSS-pixel scale (retina divided out, so sizes compare), in rows up to 2400 px wide, each labelled «device · width px».

`--click` runs in order after the page loads (and after the lazy-load scroll with `--full`), 600 ms apart; the state after the last click is captured.

Cookie banners and other overlays:

```sh
python3 shot.py URL --cookie 'cookieyes-consent=...' --hide '#preview-bar, .chat-widget'
```

`--cookie` presets a cookie on the URL's host (consent banners often can't be hidden with CSS). `--hide` injects `display: none !important` on every page load. Both apply only to the throwaway browser profile. A site-specific wrapper script is a good place for them.

Device names: any [Playwright device](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/server/deviceDescriptorsSource.json), `laptop` (1280×800), `desktop` (1440×900), `wide` (1920×1080), `iPhone Duo` / `iPhone Duo open` / `iPhone Duo open portrait` (Apple's foldable: 1398×2034 and 1878×2670 px panels at @3x, inferred from their 460/430 ppi, so 466×678, 890×626 and 626×890), or `sample` for the whole set in `SAMPLE`.

With `--selector`, fixed and sticky elements (headers, chat bubbles) are hidden so they don't cover the element.

## Layout problems as text: `--check`

No images: each URL is loaded on each device (scrolled through so lazy content loads, `--click` applied) and the problems are listed. A problem seen on several devices is printed once, with where it happens («every touch device», «every device but iPhone SE · 320 px»…). Exit code 1 when anything is found, so it fits a CI step.

```sh
python3 shot.py https://example.com https://example.com/cart -d sample --check
```

It reports:

- the page scrolling sideways, and the elements that stick out on the right (a closed drawer, wholly off-screen, is ignored);
- tap targets under 24 px on touch devices (WCAG 2.5.8, with its spacing exception and links inside running text exempt); identical ones (carousel dots) are one line with a count;
- text cut with an ellipsis or a line clamp;
- broken images;
- fixed layers covering over 25 / 50 / 75 % of the screen (cookie banners, chat bubbles; sticky galleries and sidebars are layout, not layers);
- JavaScript errors, console errors and requests answered 4xx/5xx (`NOISE` lists platform requests that always fail, such as Shopify's `sf_private_access_tokens`).

A whole site: `--sitemap N` reads `/sitemap.xml` and adds N pages of each kind (products, collections, pages, articles…), picked evenly through each list rather than the first N. Chunks of one kind (`sitemap_products_1`, `_2`…) count as one list, and the per-language copies (`/fr/sitemap_products_1.xml`) are skipped: same templates. Files listed in a sitemap (`agents.md`, feeds) are not pages and are skipped. A URL ending in `.xml` is read as the sitemap itself.

```sh
python3 shot.py https://shop.example --check --sitemap 3 -d "iPhone SE" -d "iPhone 13" -d desktop
```

With three pages or more, the problems every page shares (header, footer, cookie banner) are listed once at the top, and each page lists only what is its own.

Devices run in parallel, one browser each (`--jobs`, default 4). A page that fails to load (timeout, network error) is reported as a finding instead of ending the run.

A phone zooms out to fit a page that is too wide, so the sideways check compares with the device's width, not `innerWidth`.

## Tests

```sh
python3 test_shot.py   # the page really sees a 390 px touch viewport (Chrome and WebKit); sheet, --dark, --click and --check work
```
