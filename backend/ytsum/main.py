from __future__ import annotations

import logging
import uvicorn

logger = logging.getLogger("ytsum.main")


def run() -> None:
    logger.info("Starting YT Sum API server on http://127.0.0.1:8765")
    try:
        uvicorn.run("ytsum.api:app", host="127.0.0.1", port=8765, reload=False)
    except Exception as e:
        logger.error(f"API server failed to start: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    run()
