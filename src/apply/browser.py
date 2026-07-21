"""Playwright browser session management (sync API)."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class BrowserSession:
    """Context manager that launches Chromium and yields a page.

    Headed by default so you can watch the form fill, solve any CAPTCHA, and
    review before submit. Set headless=True for testing the plumbing.
    """

    def __init__(self, headless: bool = False, slow_mo_ms: int = 150):
        self.headless = headless
        self.slow_mo_ms = slow_mo_ms
        self._pw = None
        self._browser = None
        self._context = None
        self.page = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=self.headless, slow_mo=self.slow_mo_ms
        )
        self._context = self._browser.new_context(
            viewport={"width": 1280, "height": 1400},
            accept_downloads=False,
        )
        self.page = self._context.new_page()
        self.page.set_default_timeout(20000)
        return self

    def new_page(self):
        return self._context.new_page()

    def __exit__(self, *exc):
        for closer in (self._context, self._browser):
            try:
                if closer:
                    closer.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:  # noqa: BLE001
            pass
        return False
