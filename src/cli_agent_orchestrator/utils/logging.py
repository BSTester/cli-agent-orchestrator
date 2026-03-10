import logging
import os
import sys


def setup_logging() -> None:
    """Setup logging configuration."""
    log_level = os.getenv("CAO_LOG_LEVEL", "INFO").upper()

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    print("Server logs: stdout")
    print("For debug logs: export CAO_LOG_LEVEL=DEBUG && cao-server")
    logging.info("Logging to: stdout")
