"""Small in-process worker; SQLite remains the durable queue."""

import asyncio
import json

from muster.browser import BrowserSession, CollectionBlocked
from muster.storage import connect


class Collector:
    def __init__(self, root, browser_factory=BrowserSession, delay=3):
        self.root = root
        self.browser_factory = browser_factory
        self.delay = delay
        self.task = None
        self.collection_id = None
        self.job_id = None
        self.waiting = False
        self.pause_requested = False
        self.action = None
        self.changed = asyncio.Event()

    @property
    def active(self):
        return self.task is not None and not self.task.done()

    def start(self, collection_id):
        if self.active:
            raise ValueError("A collection is already running. Stop it before starting another.")
        with connect(self.root) as db:
            if not db.execute(
                "SELECT 1 FROM jobs WHERE collection_id=? AND removed=0 AND status='queued'",
                (collection_id,),
            ).fetchone():
                raise ValueError("There are no waiting pages. Retry a failed page first.")
        self.collection_id = collection_id
        self.pause_requested = False
        self.waiting = False
        self.task = asyncio.create_task(self.run())

    async def close(self):
        if self.active:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    def control(self, collection_id, action):
        if not self.active or self.collection_id != collection_id:
            raise ValueError("This collection is not running.")
        if action == "stop":
            self.task.cancel()
        elif action == "pause" and not self.waiting:
            self.pause_requested = True
        elif action in ("continue", "skip") and self.waiting:
            self.action = action
            self.changed.set()
        else:
            raise ValueError("This action is not available right now. Refresh the page.")

    def claim(self):
        with connect(self.root) as db:
            db.execute("BEGIN IMMEDIATE")
            job = db.execute(
                "SELECT * FROM jobs WHERE collection_id=? AND removed=0 AND status='queued' ORDER BY id LIMIT 1",
                (self.collection_id,),
            ).fetchone()
            if job:
                db.execute(
                    "UPDATE jobs SET status='collecting', error=NULL, attempts=attempts+1 WHERE id=?",
                    (job["id"],),
                )
                self.job_id = job["id"]
            return job

    def state(self, status, error=None):
        if self.job_id is not None:
            with connect(self.root) as db:
                db.execute(
                    "UPDATE jobs SET status=?, error=? WHERE id=?", (status, error, self.job_id)
                )

    def retain(self, job, metadata):
        metadata = {**metadata, "source_url": job["url"]}
        directory = self.root / "sources" / str(job["id"]) / metadata["id"]
        (directory / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        with connect(self.root) as db:
            db.execute(
                "INSERT INTO captures(id,job_id,captured_at,final_url,status,error,metadata) VALUES(?,?,?,?,?,?,?)",
                (
                    metadata["id"],
                    job["id"],
                    metadata["captured_at"],
                    metadata["final_url"],
                    metadata["status"],
                    metadata.get("error"),
                    json.dumps(metadata, ensure_ascii=False),
                ),
            )

    async def collect(self, browser, job):
        delay = await browser.allowed(job["url"])
        try:
            await browser.visit(job["url"])
        except Exception:
            if browser.policy_error:
                raise CollectionBlocked(browser.policy_error) from None
            raise
        while True:
            try:
                reason = await browser.attention()
            except Exception as exc:
                error = (
                    str(exc)
                    if isinstance(exc, RuntimeError)
                    else "The page could not be inspected. Retry it."
                )
                self.retain(job, await browser.snapshot(job["id"], "failed", error))
                self.state("failed", error)
                return delay
            if self.pause_requested:
                reason = (
                    reason
                    or "Paused at your request. Check the managed browser, then continue or skip."
                )
                self.pause_requested = False
            status = "blocked" if reason else "captured"
            self.retain(job, await browser.snapshot(job["id"], status, reason))
            self.state(status, reason)
            if not reason:
                return delay
            self.action = None
            self.changed.clear()
            self.waiting = True
            try:
                signal = asyncio.create_task(self.changed.wait())
                closed = asyncio.create_task(browser.closed.wait())
                try:
                    await asyncio.wait((signal, closed), return_when=asyncio.FIRST_COMPLETED)
                    if browser.closed.is_set():
                        raise RuntimeError("The managed browser was closed.")
                finally:
                    signal.cancel()
                    closed.cancel()
                    await asyncio.gather(signal, closed, return_exceptions=True)
            finally:
                self.waiting = False
            if self.action == "skip":
                self.state(
                    "failed",
                    "Skipped after an interruption. Original captures are retained; retry when ready.",
                )
                return delay
            # Continue inspects the current browser page, without replaying login/navigation.
            await browser.allowed(browser.page.url)
            self.state("collecting")

    async def run(self):
        try:
            job = self.claim()
            if job is None:
                return
            async with self.browser_factory(self.root) as browser:
                while job:
                    delay = self.delay
                    try:
                        delay = max(delay, await self.collect(browser, job))
                    except CollectionBlocked as exc:
                        self.state("blocked", str(exc))
                    except Exception as exc:
                        message = f"Could not collect this page ({type(exc).__name__}). Check the browser or connection and retry."
                        # A timeout can still leave useful rendered content. Retain it as FAILED,
                        # never feed it to extraction or revisit the website automatically.
                        try:
                            async with asyncio.timeout(10):
                                self.retain(
                                    job, await browser.snapshot(job["id"], "failed", message)
                                )
                        except Exception:
                            pass
                        self.state("failed", message)
                        if browser.closed.is_set():
                            break
                    self.job_id = None
                    await asyncio.sleep(delay)
                    job = self.claim()
        except asyncio.CancelledError:
            self.state(
                "failed",
                "Collection stopped. Retry this page when ready; retained captures are unchanged.",
            )
            raise
        except Exception:
            self.state(
                "failed",
                "The managed browser could not start or was closed. Install Chromium with 'python -m playwright install chromium', check that a desktop is available, then retry. Close other Muster instances using this profile.",
            )
        finally:
            self.job_id = None
            self.waiting = False
            self.pause_requested = False
