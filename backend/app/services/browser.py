"""
Shared headless browser utilities using Playwright.

Provides a managed Chromium browser instance that scrapers can use when
curl_cffi/httpx get blocked by Cloudflare, PerimeterX, or other anti-bot systems.

Usage:
    from app.services.browser import browser_fetch, browser_fetch_with_cookies

    html = await browser_fetch("https://example.com/page")
    html = await browser_fetch_with_cookies("https://example.com/api", cookies={...})
"""

import asyncio
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

_browser = None
_browser_lock = asyncio.Lock()
_last_used: float = 0.0
BROWSER_IDLE_TIMEOUT = 300  # Close browser after 5 min idle


async def _get_browser():
    """Get or create a shared Playwright Chromium browser instance."""
    global _browser, _last_used
    async with _browser_lock:
        if _browser and _browser.is_connected():
            _last_used = time.time()
            return _browser

        try:
            from playwright.async_api import async_playwright
            pw = await async_playwright().start()
            _browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-accelerated-2d-canvas",
                    "--disable-gpu",
                    "--window-size=1920,1080",
                ],
            )
            _last_used = time.time()
            logger.info("[Browser] Launched headless Chromium")
            return _browser
        except ImportError:
            logger.warning("[Browser] Playwright not installed - headless browser unavailable")
            return None
        except Exception as e:
            logger.warning(f"[Browser] Failed to launch browser: {e}")
            return None


async def browser_fetch(
    url: str,
    wait_selector: Optional[str] = None,
    wait_time: int = 3000,
    timeout: int = 20000,
    cookies: Optional[list[dict]] = None,
    extra_headers: Optional[dict] = None,
    intercept_json: bool = False,
) -> Optional[str]:
    """Fetch a page using headless Chromium, returning the full HTML.

    Args:
        url: URL to navigate to.
        wait_selector: CSS selector to wait for before capturing HTML.
        wait_time: Additional time (ms) to wait after page load.
        timeout: Navigation timeout in ms.
        cookies: List of cookie dicts [{name, value, domain, path}].
        extra_headers: Additional HTTP headers.
        intercept_json: If True, capture and return JSON responses from XHR/fetch.

    Returns:
        Page HTML content, or None on failure.
    """
    browser = await _get_browser()
    if not browser:
        return None

    context = None
    try:
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/New_York",
        )

        if cookies:
            await context.add_cookies(cookies)

        page = await context.new_page()

        if extra_headers:
            await page.set_extra_http_headers(extra_headers)

        # Stealth: mask webdriver detection
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
            window.chrome = { runtime: {} };
        """)

        json_responses = []
        if intercept_json:
            async def _on_response(response):
                ct = response.headers.get("content-type", "")
                if "application/json" in ct:
                    try:
                        body = await response.text()
                        json_responses.append(body)
                    except Exception:
                        pass
            page.on("response", _on_response)

        await page.goto(url, wait_until="domcontentloaded", timeout=timeout)

        if wait_selector:
            try:
                await page.wait_for_selector(wait_selector, timeout=wait_time)
            except Exception:
                pass
        else:
            await page.wait_for_timeout(wait_time)

        if intercept_json and json_responses:
            return json_responses[-1]

        html = await page.content()
        logger.info(f"[Browser] Fetched {len(html)} bytes from {url[:60]}")
        return html

    except Exception as e:
        logger.warning(f"[Browser] Failed to fetch {url[:60]}: {e}")
        return None
    finally:
        if context:
            try:
                await context.close()
            except Exception:
                pass


async def browser_fetch_api(
    page_url: str,
    api_pattern: str,
    cookies: Optional[list[dict]] = None,
    timeout: int = 20000,
    wait_time: int = 5000,
) -> Optional[str]:
    """Navigate to a page and intercept a specific API call matching a URL pattern.

    Useful for capturing XHR/fetch responses that contain the data we need.

    Args:
        page_url: URL to navigate to (triggers the API call).
        api_pattern: Substring to match in intercepted response URLs.
        cookies: Browser cookies to set.
        timeout: Navigation timeout in ms.
        wait_time: How long to wait for the API call after page load.

    Returns:
        JSON response body as string, or None.
    """
    browser = await _get_browser()
    if not browser:
        return None

    context = None
    try:
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="en-US",
        )

        if cookies:
            await context.add_cookies(cookies)

        page = await context.new_page()
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """)

        captured = []

        async def _on_response(response):
            if api_pattern in response.url:
                try:
                    body = await response.text()
                    captured.append(body)
                except Exception:
                    pass

        page.on("response", _on_response)

        await page.goto(page_url, wait_until="domcontentloaded", timeout=timeout)
        await page.wait_for_timeout(wait_time)

        if captured:
            logger.info(f"[Browser] Intercepted {len(captured)} API response(s) matching '{api_pattern}'")
            return captured[0]

        return None

    except Exception as e:
        logger.warning(f"[Browser] API intercept failed for {page_url[:60]}: {e}")
        return None
    finally:
        if context:
            try:
                await context.close()
            except Exception:
                pass


async def close_browser():
    """Shut down the shared browser instance."""
    global _browser
    async with _browser_lock:
        if _browser:
            try:
                await _browser.close()
            except Exception:
                pass
            _browser = None
            logger.info("[Browser] Closed headless browser")
