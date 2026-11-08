from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

SERVER_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = SERVER_DIR / ".env"


class Settings(BaseSettings):
    # Unknown keys in .env (old or future ones) are ignored.
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    demo_persona: str = "alex"  # which generated customer scripts/load_customer.py loads by default
    random_seed: int = 42
    # Last day of generated history (YYYY-MM-DD). Empty = today. Pin it so every reload and every
    # teammate gets identical data: shifting the window by a day changes every random draw.
    demo_end_date: str = ""

    # SQLite (relative paths resolve against server/)
    sqlite_path: str = "./data/copilot.db"  # anonymized working data
    private_db_path: str = "./data/private.db"  # alias <-> real name lookup (level 0)

    frontend_origin: str = "http://localhost:5173"
    log_level: str = "INFO"
    log_body_max_chars: int = 1000

    @staticmethod
    def _resolve(p: str) -> Path:
        path = Path(p)
        return path if path.is_absolute() else (SERVER_DIR / path).resolve()

    @property
    def sqlite_file(self) -> Path:
        return self._resolve(self.sqlite_path)

    @property
    def private_file(self) -> Path:
        return self._resolve(self.private_db_path)


settings = Settings()
