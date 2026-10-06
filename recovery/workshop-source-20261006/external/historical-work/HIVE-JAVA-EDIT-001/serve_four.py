"""Serve the patched Workshop on loopback for a keyless local diagnostic pilot."""

import os
import sys
from pathlib import Path

import uvicorn

from local_harness import (
    MODEL, WORKSHOP, PreflightFailure, approved_environment, model_inventory,
    no_cloud_key, reference_freeze,
)


def main():
    no_cloud_key()
    reference = reference_freeze()
    approved = approved_environment(reference)
    model = model_inventory()
    if model["digest"] != "9ec8897f747e246e970bc5cfdda85d22f1123dc2e3d34978a010a75968716849":
        raise PreflightFailure("The selected local model changed")
    print("FOUR_TASK_SERVICE_PREFLIGHT_OK key_absent=True image="
          + approved["verifier_image_id"], flush=True)
    os.chdir(WORKSHOP)
    sys.path.insert(0, str(WORKSHOP))
    import app  # noqa: E402
    uvicorn.run(app.app, host="127.0.0.1", port=8767, reload=False, log_level="warning")


if __name__ == "__main__":
    main()
