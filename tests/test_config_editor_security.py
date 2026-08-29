from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import Error as PlaywrightError, sync_playwright


def test_imported_type_is_whitelisted_before_rendering():
    editor = Path(__file__).parents[1] / "config-editor.html"
    malicious_type = '" onmouseover="window.__xss = true" data-x="'

    with sync_playwright() as playwright_api:
        try:
            browser = playwright_api.chromium.launch(
                headless=True,
                chromium_sandbox=True,
            )
        except PlaywrightError as exc:
            pytest.skip(f"Chromium is not installed: {exc}")
        page = browser.new_page()
        page.goto(editor.as_uri())
        page.evaluate(
            """(typeValue) => loadConfig({body: [{type: typeValue, src: 'example'}]})""",
            malicious_type,
        )

        assert page.evaluate("window.__xss === true") is False
        assert page.locator("[onmouseover]").count() == 0
        assert page.locator(".source-card").count() == 1
        assert page.locator(".source-type-badge").first.inner_text() == "none"
        browser.close()


def test_valid_imported_type_remains_usable():
    editor = Path(__file__).parents[1] / "config-editor.html"

    with sync_playwright() as playwright_api:
        try:
            browser = playwright_api.chromium.launch(
                headless=True,
                chromium_sandbox=True,
            )
        except PlaywrightError as exc:
            pytest.skip(f"Chromium is not installed: {exc}")
        page = browser.new_page()
        page.goto(editor.as_uri())
        page.evaluate(
            """() => loadConfig({body: [{type: 'mail', src: 'example'}]})"""
        )
        assert page.locator(".source-type-badge").first.inner_text() == "mail"
        browser.close()
