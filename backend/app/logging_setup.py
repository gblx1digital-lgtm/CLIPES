from __future__ import annotations

import logging
import logging.handlers

from .config import REPO_DIR, get_settings


def setup_logging(component: str) -> None:
    s = get_settings()
    log_dir = REPO_DIR / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s [%(name)s] %(message)s")
    root = logging.getLogger()
    root.setLevel(s.log_level.upper())
    if not any(getattr(h, "_clipes", False) for h in root.handlers):
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        console._clipes = True  # type: ignore[attr-defined]
        file = logging.handlers.RotatingFileHandler(log_dir / f"{component}.log", maxBytes=10_000_000, backupCount=5,
                                                    encoding="utf-8")
        file.setFormatter(fmt)
        file._clipes = True  # type: ignore[attr-defined]
        root.addHandler(console)
        root.addHandler(file)
    for noisy in ("httpx", "httpcore", "anthropic._base_client"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
