"""
Configuration du logging centralisé.

Tous les modules doivent utiliser :
    from src.core.logging import get_logger
    logger = get_logger(__name__)
"""

import logging
import sys


def get_logger(name: str) -> logging.Logger:
    """
    Retourne un logger configuré.

    Format :
        2025-01-15 14:30:00 | INFO  | src.engine.smc | Message
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    return logger