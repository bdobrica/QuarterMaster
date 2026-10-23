# Third-party software and model licenses

QuarterMaster code is distributed under [Apache-2.0](../LICENSE). This does not relicense dependencies, uploaded materials or model weights.

## Bundled browser dependency

HTMX **2.0.11** is vendored unchanged in [htmx.min.js](../quartermaster/ui/static/vendor/htmx.min.js), under the [Zero-Clause BSD license](../quartermaster/ui/static/vendor/HTMX-LICENSE.txt). No Node build or CDN connection is required at runtime.

Upstream: [HTMX installation documentation](https://htmx.org/docs/) and [versioned distribution](https://cdn.jsdelivr.net/npm/htmx.org@2.0.11/dist/htmx.min.js). The downloaded bytes were checked against the published SHA-384 integrity value:

```text
sha384-2OatzQy1H+Zd/IIrjr1TcuDGqLXeHhbooAyJY1KdQMKnr4LZ22k31GBLdYKHmVjg
sha256-d6fdc75f204e6bdefa99b69bf1e6d4ac69b8a364f77929f45c13476b4000f717
```

The CPU smoke test checks the SHA-256 digest. When updating, download both the asset and its license and verify the new published integrity value.

## Python and container dependencies

[pyproject.toml](../pyproject.toml) pins direct dependencies and [uv.lock](../uv.lock) pins transitive packages and distribution hashes. Each package retains its upstream license. The official Python image includes Python and Debian components with their own terms. Preserve these notices when redistributing an image; the project license alone does not cover them.

Runtime packages are limited to FastAPI/Uvicorn for HTTP, Jinja2 for server-rendered HTML, Pydantic for public validation, pydantic-settings for environment/`.env` loading and secret masking, and python-multipart for browser forms. SQLite uses Python's standard library. Pytest, HTTPX2 (the installed Starlette TestClient's supported client) and Ruff are development-only. There is no GPU or provider SDK dependency in Milestone 0.

## Models and uploaded materials

Milestone 0 ships **no model weights, adapters, trainer or inference engine**. The Qwen example in [PLAN.md](../PLAN.md) is a candidate, not a verified model/license selection. Milestone 1 must record the exact upstream repository, revision, license and tested redistribution conditions before weights are distributed. Adapter training and format conversion do not remove base-model obligations.

Future exports must preserve applicable model/runtime license notices and exact revision provenance. Uploaded source materials remain subject to their owners' rights; approving a lesson does not grant redistribution rights over its sources.
