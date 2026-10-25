"""One visible, managed browser. Pages have no access to application tools."""

import asyncio
import ipaddress
import json
import socket
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
from uuid import uuid4

from playwright.async_api import async_playwright

from muster.imports import normalize_url


class CollectionBlocked(Exception):
    pass


async def public_url(url):
    """Check navigation, redirects and subresources, not just imported URLs."""
    if not normalize_url(url):
        return False
    try:
        addresses = await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(
                urlsplit(url).hostname, None, type=socket.SOCK_STREAM
            ),
            10,
        )
        return bool(addresses) and all(
            ipaddress.ip_address(address[4][0]).is_global for address in addresses
        )
    except (TimeoutError, OSError, ValueError):
        return False


class BrowserSession:
    def __init__(self, root: Path):
        self.root = root
        self.context = None
        self.playwright = None
        self.page = None
        self.responses = {}
        self.http_status = None
        self.robots = {}
        self.hosts = {}
        self.policy_error = None
        self.closed = asyncio.Event()

    async def __aenter__(self):
        self.playwright = await async_playwright().start()
        try:
            self.context = await self.playwright.chromium.launch_persistent_context(
                str(self.root / "browser-profile"),
                headless=False,
                viewport={"width": 1366, "height": 900},
                accept_downloads=False,
                service_workers="block",
            )
            self.context.set_default_timeout(15000)
            await self.context.route("**/*", self.guard)
            await self.context.route_web_socket("**/*", lambda socket: socket.close())
            self.page = (
                self.context.pages[0] if self.context.pages else await self.context.new_page()
            )
            self.page.on("response", self.on_response)
            self.context.on("close", lambda _: self.closed.set())
            self.page.on("close", lambda _: self.closed.set())
            self.page.on("dialog", lambda dialog: asyncio.create_task(dialog.dismiss()))
            return self
        except BaseException:
            await self.__aexit__(None, None, None)
            raise

    async def __aexit__(self, *args):
        try:
            if self.context:
                await self.context.close()
        finally:
            if self.playwright:
                await self.playwright.stop()

    async def guard(self, route):
        url = route.request.url
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self.hosts:
            self.hosts[origin] = await public_url(url)
        if not self.hosts[origin]:
            if route.request.is_navigation_request():
                self.policy_error = "This page tried to open a local or unsupported address."
            await route.abort()
            return
        # Check every top-level navigation, including manual sign-in and redirects.
        if route.request.is_navigation_request() and route.request.frame.parent_frame is None:
            try:
                await self.allowed(url)
            except Exception:
                self.policy_error = "Collection is not allowed here, or the site's collection rules could not be checked."
                await route.abort()
                return
        await route.continue_()

    async def allowed(self, url):
        if not await public_url(url):
            raise CollectionBlocked("Only public web addresses may be collected.")
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self.robots:
            target = origin + "/robots.txt"
            for _ in range(5):
                if not await public_url(target):
                    raise CollectionBlocked(
                        "The site's collection rules redirect to an unsupported address."
                    )
                response = await self.context.request.get(target, max_redirects=0, timeout=20000)
                try:
                    if response.status in (301, 302, 303, 307, 308):
                        target = urljoin(target, response.headers.get("location", ""))
                        continue
                    if response.status in (404, 410):
                        text = "User-agent: *\nAllow: /"
                    elif response.status == 200:
                        text = await response.text()
                        if len(text) > 1024 * 1024 or "<html" in text[:1000].lower():
                            raise CollectionBlocked(
                                "The site's collection rules could not be read."
                            )
                    else:
                        raise CollectionBlocked(
                            "The site's collection rules could not be checked. Try later or use another source."
                        )
                    parser = RobotFileParser()
                    parser.parse(text.splitlines())
                    self.robots[origin] = parser
                    break
                finally:
                    await response.dispose()
            else:
                raise CollectionBlocked("Too many redirects checking the site's collection rules.")
        rules = self.robots[origin]
        # Use the browser's actual identity; no stealth user agent or challenge bypass.
        if not rules.can_fetch("*", url):
            raise CollectionBlocked("This site's collection rules do not allow this page.")
        return max(3, rules.crawl_delay("*") or 0)

    def on_response(self, response):
        if response.request.is_navigation_request() and response.frame == self.page.main_frame:
            self.http_status = response.status
            self.policy_error = None
        if response.request.resource_type == "image" and len(self.responses) < 200:
            self.responses[response.url] = response

    async def visit(self, url):
        self.responses.clear()
        self.http_status = None
        self.policy_error = None
        self.hosts.clear()
        await self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
        await self.page.wait_for_timeout(2000)
        # Bounded scrolling reveals common lazy-loaded listing galleries.
        for _ in range(3):
            await self.page.mouse.wheel(0, 700)
            await self.page.wait_for_timeout(350)
        await self.page.evaluate("window.scrollTo(0, 0)")

    async def attention(self):
        if self.policy_error:
            return self.policy_error
        if self.http_status in (401, 403, 429):
            return f"This site returned HTTP {self.http_status}. Check the browser; sign in if permitted, or skip this page."
        title = (await self.page.title()).lower()
        text = (await self.page.locator("body").inner_text())[:20000].lower()
        if "captcha" in title or any(
            phrase in title or phrase in text[:3000]
            for phrase in (
                "access denied",
                "verify you are human",
                "verify that you are human",
                "verify that you're human",
                "confirm you are human",
                "checking your browser",
                "just a moment",
                "enable javascript and cookies",
                "attention required",
                "unusual traffic",
                "complete the captcha",
                "verifică dacă ești",
                "verifica daca esti",
            )
        ):
            return "This site needs your attention in the browser. Muster will not bypass access restrictions."
        if await self.page.locator('input[type="password"]:visible').count():
            return "Sign in in the managed browser if you have permission, then continue here."
        if self.http_status is not None and self.http_status >= 400:
            raise RuntimeError(
                f"The page returned HTTP {self.http_status}. Check the link or try later."
            )
        if not text.strip():
            raise RuntimeError("The page has no readable content. Check the browser and retry.")
        if self.http_status is None:
            raise RuntimeError("No successful page response was received.")
        return None

    async def snapshot(self, job_id, status, error=None):
        capture_id = uuid4().hex
        directory = self.root / "sources" / str(job_id) / capture_id
        directory.mkdir(parents=True)
        captured_at = datetime.now(UTC).isoformat()
        # Retain rendered HTML but remove entered passwords. Never store headers/cookies.
        html = await self.page.evaluate("""() => {
            const copy = document.documentElement.cloneNode(true);
            copy.querySelectorAll('input[type=password]').forEach(el => el.removeAttribute('value'));
            return '<!doctype html>\\n' + copy.outerHTML;
        }""")
        (directory / "page.html").write_text(html, encoding="utf-8")
        await self.page.screenshot(
            path=str(directory / "screenshot.png"),
            full_page=True,
            timeout=30000,
            mask=await self.page.locator('input[type="password"]').all(),
        )
        images = []
        warnings = []
        candidates = await self.page.evaluate("""() => {
            const large = [...document.images].filter(img =>
                img.naturalWidth >= 240 && img.naturalHeight >= 160 &&
                !img.closest('nav,header,footer,aside,.gm-style,[data-testid*="map" i]'));
            const gallery = large.filter(img => img.closest(
                '[data-cy*="gallery" i],[data-testid*="gallery" i],[class*="gallery" i],[class*="carousel" i]'));
            return (gallery.length ? gallery : large).map(img => ({
                url:img.currentSrc || img.src, alt:img.alt,
                width:img.naturalWidth,height:img.naturalHeight}));
        }""")
        seen = set()
        mime_extensions = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/gif": ".gif",
            "image/avif": ".avif",
        }
        for candidate in candidates:
            url = candidate["url"]
            if url in seen or len(images) >= 12:
                continue
            seen.add(url)
            response = self.responses.get(url)
            if not response or not response.ok:
                warnings.append("A displayed image was unavailable from the browser cache.")
                continue
            mime = response.headers.get("content-type", "").split(";")[0]
            if mime not in mime_extensions:
                continue
            try:
                body = await asyncio.wait_for(response.body(), 10)
                if len(body) > 8 * 1024 * 1024:
                    warnings.append("An image larger than 8 MB was skipped.")
                    continue
                filename = f"image-{len(images) + 1}{mime_extensions[mime]}"
                (directory / filename).write_bytes(body)
                images.append({**candidate, "file": filename, "mime": mime})
            except Exception:
                warnings.append(
                    "A displayed image could not be retained. It may still appear in the screenshot."
                )
        if not images:
            warnings.append(
                "No large gallery images were retained. Inspect the screenshot before using this source."
            )
        metadata = {
            "id": capture_id,
            "job_id": job_id,
            "captured_at": captured_at,
            "final_url": self.page.url,
            "title": await self.page.title(),
            "http_status": self.http_status,
            "status": status,
            "error": error,
            "html": "page.html",
            "screenshot": "screenshot.png",
            "images": images,
            "warnings": list(dict.fromkeys(warnings)),
            "collector": "Muster / Playwright Chromium",
        }
        (directory / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return metadata
