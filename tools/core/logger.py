import logging
from datetime import datetime
from pathlib import Path


def setup_logger(name: str = "reporte-marfil") -> logging.Logger:
    """Configura logger con salida a consola y archivo diario."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    # Console
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

    # File
    logs_dir = Path(__file__).resolve().parent.parent.parent / "logs"
    logs_dir.mkdir(exist_ok=True)
    file_handler = logging.FileHandler(
        logs_dir / f"{datetime.now().strftime('%Y-%m-%d')}.log",
        encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
