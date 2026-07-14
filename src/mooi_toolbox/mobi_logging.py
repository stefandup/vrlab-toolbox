import logging
import os
import sys
from pathlib import Path


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
        format="{asctime} - {name} - {levelname} - {message}",
        style="{",
        datefmt="%Y-%m-%d %H:%M",
        level=logging.INFO,
    )


def log_section(logger, title: str, width: int = 80) -> None:
    border = "-" * width
    logger.info("")
    logger.info(border)
    logger.info(title)
    logger.info(border)
