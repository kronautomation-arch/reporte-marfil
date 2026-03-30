import os
from pathlib import Path
from dotenv import load_dotenv


def load_env():
    """Carga variables de entorno desde .env en la raíz del proyecto."""
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    load_dotenv(env_path)


def get_env(key: str, required: bool = True) -> str:
    """Obtiene una variable de entorno. Lanza error si es requerida y no existe."""
    value = os.getenv(key)
    if required and not value:
        raise EnvironmentError(f"Variable de entorno requerida no encontrada: {key}")
    return value or ""
