"""Review publication readiness and download a checked, immutable local version."""

import zipfile

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from jsonschema import ValidationError
from starlette.concurrency import run_in_threadpool

from muster import publication as pub


def register_publication_routes(app, root, render):
    def home(request, cid, message=None, status_code=200):
        try:
            data = pub.overview(root, cid)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        return render(request, "publish.html", **data, message=message, status_code=status_code)

    @app.get("/collections/{cid}/publish")
    def overview(request: Request, cid: int):
        return home(request, cid)

    @app.post("/collections/{cid}/publish/exclusions/{jid}/{action}")
    async def exclusion(request: Request, cid: int, jid: int, action: str):
        form = await request.form()
        try:
            if action == "exclude":
                pub.exclude(root, cid, jid, form.get("reason", ""))
            elif action == "include":
                pub.include(root, cid, jid)
            else:
                raise HTTPException(404, "Action not found")
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            return home(request, cid, str(exc), 400)
        return RedirectResponse(f"/collections/{cid}/publish", 303)

    @app.post("/collections/{cid}/publish")
    async def publish(request: Request, cid: int):
        form = await request.form()
        try:
            if form.get("confirm") != "yes":
                raise ValueError(
                    "Confirm publishing the current examples and saved knowledge articles."
                )
            pid = await run_in_threadpool(pub.publish, root, cid, form.get("fingerprint", ""))
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except pub.PublicationConflict as exc:
            return home(request, cid, str(exc), 409)
        except (ValueError, OSError, ValidationError) as exc:
            # Avoid huge validation dumps containing entire source payloads.
            message = (
                "An example no longer matches the accepted fields."
                if isinstance(exc, ValidationError)
                else str(exc)
            )
            return home(request, cid, "Publication was not created. " + message, 400)
        return RedirectResponse(f"/collections/{cid}/publications/{pid}", 303)

    def version(cid, pid):
        try:
            return pub.get_publication(root, cid, pid)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (ValueError, OSError, ValidationError, KeyError) as exc:
            reason = (
                "An example does not match the accepted fields."
                if isinstance(exc, ValidationError)
                else "A published file is missing or unreadable."
                if isinstance(exc, OSError)
                else "Publication metadata is incomplete."
                if isinstance(exc, KeyError)
                else str(exc)
            )
            raise HTTPException(409, "Could not open this published version: " + reason) from exc

    @app.get("/collections/{cid}/publications/{pid}")
    def published(request: Request, cid: int, pid: str):
        data = version(cid, pid)
        return render(request, "published.html", publication=data, cid=cid)

    @app.get("/collections/{cid}/publications/{pid}/download")
    def download(cid: int, pid: str):
        data = version(cid, pid)
        folder = pub.safe_path(root, data["path"])
        archive = folder.with_suffix(".zip")
        # Verify the downloadable archive against the checked bundle, not just its existence.
        try:
            with zipfile.ZipFile(archive) as z:
                expected = {
                    f"collection-{cid}-v{data['version']}/"
                    + str(p.relative_to(folder).as_posix()): p
                    for p in folder.rglob("*")
                    if p.is_file()
                }
                if len(z.infolist()) != len(expected) or set(z.namelist()) != set(expected):
                    raise ValueError("Archive inventory changed")
                for name, path in expected.items():
                    if pub.digest(z.read(name)) != pub.digest(path.read_bytes()):
                        raise ValueError("Archive contents changed")
        except (OSError, ValueError, zipfile.BadZipFile, KeyError) as exc:
            raise HTTPException(
                409, "The publication archive failed validation. Restore your publication backup."
            ) from exc
        return FileResponse(
            archive,
            media_type="application/zip",
            filename=f"collection-{cid}-v{data['version']}.zip",
        )
