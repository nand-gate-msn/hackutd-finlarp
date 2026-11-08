from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVER_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = SERVER_DIR / ".env"


class Settings(BaseSettings):
    # Unknown keys in .env (old or future ones) are ignored.
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    demo_persona: str = "alex"  # which generated customer scripts/load_customer.py loads by default
    random_seed: int = 42
    monte_carlo_runs: int = 5000
    # Last day of generated history (YYYY-MM-DD). Empty = today. Pin it so every reload and every
    # teammate gets identical data: shifting the window by a day changes every random draw.
    demo_end_date: str = ""

    # SQLite (relative paths resolve against server/)
    sqlite_path: str = "./data/copilot.db"  # anonymized working data
    private_db_path: str = "./data/private.db"  # alias <-> real name lookup (level 0)

    # NVIDIA Nemotron (OpenAI-compatible endpoint)
    nvidia_api_key: SecretStr = SecretStr("")
    llm_base_url: str = "https://integrate.api.nvidia.com/v1"
    nemotron_super_model: str = ""  # strong model: Explainer, Action
    nemotron_lightning_model: str = ""  # fast model: Planner, Critic
    llm_temperature: float = 1.0
    llm_top_p: float = 0.95
    llm_temperature_precise: float = 0.2  # Planner and Critic: exact structure and steady judgement
    llm_timeout_seconds: float = 30.0
    llm_requests_per_minute: int = 40  # NVIDIA free tier is ~40/min per key
    llm_retries: int = 1  # extra attempts after the first, per call
    llm_breaker_failures: int = 3  # consecutive network/server failures before we stop waiting on NVIDIA
    llm_breaker_cooldown_seconds: float = 20.0
    critic_max_retries: int = 2  # times the Critic may send proposals back to Action

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
