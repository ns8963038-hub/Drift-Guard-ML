"""Render every screen in a real browser and check what a status code cannot.

An HTTP 200 says a view did not raise. It says nothing about a chart drawn at
16 pixels wide, a sidebar that squeezes the content column to a strip, or a
table that pushes the page sideways. This script opens each screen in Chromium
across two themes and four viewports, screenshots it, and asserts the things
that only exist visually:

  * the page body never scrolls horizontally
  * no console or JavaScript errors
  * the distribution chart's canvas has real dimensions

Optional tooling — not a project dependency:

    pip install playwright && playwright install chromium
    python manage.py runserver 127.0.0.1:8899 --noreload   # in another shell
    python scripts/visual_check.py

Screenshots land in /tmp/shots/ for eyeballing.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright  # noqa: E402

BASE = "http://127.0.0.1:8899"


def _run_id():
    """The newest run with drift, so the screens have something to show."""
    import os

    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    os.environ["SCHEDULER_ENABLED"] = "False"
    django.setup()
    from registry.models import MLModel

    model = MLModel.objects.get(slug=SLUG)
    run = (
        model.runs.filter(status="COMPLETED", features_high__gt=0)
        .order_by("-created_at")
        .first()
        or model.runs.first()
    )
    return run.pk


SLUG = "customer-churn-model"

PAGES = [
    ("dashboard", "/"),
    ("models-list", "/models/"),
    ("model-overview", f"/models/{SLUG}/"),
    ("versions", f"/models/{SLUG}/versions/"),
    ("compare", f"/models/{SLUG}/compare/"),
    ("history", f"/models/{SLUG}/history/"),
    ("drift-tab", f"/models/{SLUG}/drift/"),
    ("quality-tab", f"/models/{SLUG}/quality/"),
    ("simulator", f"/models/{SLUG}/simulator/"),
    ("thresholds", f"/alerts/thresholds/{SLUG}/"),
    ("train", f"/models/{SLUG}/train/"),
    ("batch-upload", f"/models/{SLUG}/batches/new/"),
    ("alerts", "/alerts/"),
    ("recommendations", "/alerts/recommendations/"),
    ("admin-users", "/admin-panel/users/"),
]


def run(theme, width, height, tag, run_pk):
    problems = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": width, "height": height})
        page = ctx.new_page()
        errors = []
        page.on(
            "console", lambda m: errors.append(m.text) if m.type == "error" else None
        )
        page.on("pageerror", lambda e: errors.append(f"JS: {e}"))

        page.goto(f"{BASE}/login/")
        page.fill("input[name=username]", "admin")
        page.fill("input[name=password]", "driftguard123")
        page.click("button[type=submit], input[type=submit]")
        page.wait_for_load_state("networkidle")

        if theme == "dark":
            page.evaluate("document.documentElement.setAttribute('data-theme','dark')")

        for name, path in PAGES:
            errors.clear()
            page.goto(f"{BASE}{path}")
            page.wait_for_load_state("networkidle")
            if theme == "dark":
                page.evaluate(
                    "document.documentElement.setAttribute('data-theme','dark')"
                )
                page.wait_for_timeout(200)
            page.screenshot(path=f"/tmp/shots/{tag}-{name}.png", full_page=True)

            # horizontal overflow: the page body must never scroll sideways
            overflow = page.evaluate(
                "Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth)"
            )
            if overflow > 2:
                problems.append(
                    f"{tag}/{name}: body overflows horizontally by {overflow}px"
                )
            for e in errors:
                if "favicon" not in e.lower():
                    problems.append(f"{tag}/{name}: console error: {e[:110]}")

        # run + feature detail — navigate directly rather than clicking a row
        RUN = run_pk
        if True:
            page.goto(f"{BASE}/runs/{RUN}/")
            page.wait_for_load_state("networkidle")
            if theme == "dark":
                page.evaluate(
                    "document.documentElement.setAttribute('data-theme','dark')"
                )
                page.wait_for_timeout(200)
            page.screenshot(path=f"/tmp/shots/{tag}-run-detail.png", full_page=True)
            ov = page.evaluate(
                "Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth)"
            )
            if ov > 2:
                problems.append(f"{tag}/run-detail: overflows by {ov}px")

            if True:
                errors.clear()
                page.goto(f"{BASE}/runs/{RUN}/features/MonthlyCharges/")
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(1200)  # let the chart draw
                if theme == "dark":
                    page.evaluate(
                        "document.documentElement.setAttribute('data-theme','dark')"
                    )
                    page.wait_for_timeout(300)
                page.screenshot(
                    path=f"/tmp/shots/{tag}-feature-detail.png", full_page=True
                )
                canvas = page.evaluate(
                    """() => {
                    const c = document.getElementById('distributionChart');
                    if (!c) return 'MISSING';
                    return c.width > 0 && c.height > 0 ? `${c.width}x${c.height}` : 'ZERO-SIZE';
                }"""
                )
                (
                    problems.append(f"{tag}/feature-detail: chart canvas {canvas}")
                    if canvas in ("MISSING", "ZERO-SIZE")
                    else None
                )
                print(f"    chart canvas: {canvas}")
                for e in errors:
                    if "favicon" not in e.lower():
                        problems.append(
                            f"{tag}/feature-detail: console error: {e[:110]}"
                        )
        browser.close()
    return problems


if __name__ == "__main__":
    # Query before Playwright starts: Django rejects synchronous ORM calls made
    # from inside its context.
    run_pk = _run_id()
    allp = []
    for theme, w, h, tag in [
        ("light", 1440, 900, "light-desktop"),
        ("dark", 1440, 900, "dark-desktop"),
        ("light", 768, 1000, "light-tablet"),
        ("light", 390, 900, "light-mobile"),
    ]:
        print(f"  {tag} ({w}x{h}, {theme})")
        allp += run(theme, w, h, tag, run_pk)
    print()
    if allp:
        print(f"  {len(allp)} PROBLEM(S):")
        for p in allp:
            print(f"    {p}")
    else:
        print("  no overflow, no console errors")
