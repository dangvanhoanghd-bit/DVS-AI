from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler

def configure_logging() -> None:
    Path("logs").mkdir(exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if root.handlers:
        return
    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )
    fh = RotatingFileHandler(
        "logs/dvs_ai.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)
