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

The repository ships **no model weights or adapters**. The opt-in Milestone 1 spike selects
`Qwen/Qwen3.5-0.8B`, upstream revision `2fc06364715b967f1860aea9cf38778875588b17`, under
the upstream Apache-2.0 license. Its downloaded snapshot includes the original license, and the
spike bundle copies it unchanged as `LICENSE.model`. Model and adapter bytes remain under ignored
local artifact storage. Training or format conversion does not remove base-model obligations.
See the [exact pins, reproduction steps and verification scope](milestone-1.md).

The optional trainer has its own [locked dependencies](../trainer/uv.lock), including PyTorch,
Transformers, TRL and PEFT. CUDA wheels retain NVIDIA licensing; the project license does not
relicense them or a host GPU driver. Explicit WSL GPU mode mounts the installed host driver
read-only for local training; those driver bytes are not bundled in an exported model.

The CPU runtime uses llama.cpp revision `1a24df163920a4744a95373d178d790b72a9bb2f` (MIT), built
from its hashed source archive. The runtime image preserves the upstream license and vendor
sources/notices, including licenses embedded in headers, under `/licenses/`. Python and Debian
components keep their own image notices. No NVIDIA runtime or trainer dependencies are installed
in the standalone CPU runtime.

Future exports must preserve applicable model/runtime license notices and exact revision provenance. Uploaded source materials remain subject to their owners' rights; approving a lesson does not grant redistribution rights over its sources.
