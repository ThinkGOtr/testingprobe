"""toolchain-worker skeleton: only /health in F0."""

import uvicorn

from toolchain_common import check_node, check_playwright, create_app

app = create_app("toolchain-worker", {"node": check_node, "playwright": check_playwright})


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8100)
