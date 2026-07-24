import logging
import os
import sys
from pathlib import Path

LOG_FORMAT = "{asctime} - {name} - {levelname} - {message}"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M"


# Configure logging
def init(caller_file):
    if getattr(sys, "frozen", False):
        PROJECT_ROOT = Path(sys.executable).resolve().parent
    else:
        PROJECT_ROOT = Path(caller_file).resolve().parents[3]

    LOG_DIR = PROJECT_ROOT / "logs"

    if not os.path.exists(LOG_DIR):
        os.mkdir(LOG_DIR)

    LOG_FILE = LOG_DIR / f"{Path(caller_file).stem}.log"

    logging.basicConfig(
        filename=LOG_FILE,
        encoding="utf-8",
        filemode="a",
        format=LOG_FORMAT,
        style="{",
        datefmt=LOG_DATE_FORMAT,
        level=logging.INFO,
    )


def log_section(logger, title: str, width: int = 80) -> None:
    border = "-" * width
    logger.info("")
    logger.info(border)
    logger.info(title)
    logger.info(border)
