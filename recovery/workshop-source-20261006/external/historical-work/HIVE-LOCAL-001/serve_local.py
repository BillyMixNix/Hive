"""Launch the keyless local Workshop after same-process non-model preflight."""

from __future__ import annotations

import os
import sys

import uvicorn

from local_harness import (
    PORT, PreflightFailure, approved_environment, model_inventory,
    no_cloud_key, reference_freeze,
)


def main() -> None:
    no_cloud_key()
    reference = reference_freeze()
    approved_environment(reference)
    model = model_inventory()
    if model["digest"] != "9ec8897f747e246e970bc5cfdda85d22f1123dc2e3d34978a010a75968716849":
        raise PreflightFailure("Selected installed model changed")
    print("LOCAL_SERVICE_PREFLIGHT_OK key_absent=True docker_and_cache_valid=True", flush=True)
    os.chdir(__import__("pathlib").Path(__file__).resolve().parent / "workshop")
    sys.path.insert(0, os.getcwd())
    import app  # noqa: E402
    uvicorn.run(app.app, host="127.0.0.1", port=PORT, reload=False, log_level="warning")


if __name__ == "__main__":
    main()
