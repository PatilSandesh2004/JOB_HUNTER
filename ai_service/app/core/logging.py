"""Central logging configuration."""

import logging

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(level=level.upper(), format=LOG_FORMAT)
    # Third-party clients are chatty at INFO.
    for noisy in ("httpx", "httpcore", "groq._base_client"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
