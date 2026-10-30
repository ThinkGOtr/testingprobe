"""test-runner control API skeleton: only /health in F0."""

import uvicorn

from toolchain_common import check_playwright, create_app

app = create_app("test-runner", {"playwright": check_playwright})


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8200)
