from functools import lru_cache
import os

from pydantic_settings import BaseSettings, SettingsConfigDict

_STREAMLIT_SECRET_KEYS = (
    "OPENROUTER_API_KEY",
    "OPENROUTER_VISION_MODEL",
    "OPENROUTER_IMAGE_MODEL",
    "TRYON_API_KEY",
    "CORS_ORIGINS",
)


def _apply_streamlit_secrets() -> None:
    """Copy Community Cloud / local st.secrets into env for pydantic Settings."""
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        if get_script_run_ctx() is None:
            return
        import streamlit as st
    except Exception:
        return

    try:
        secrets = st.secrets
    except Exception:
        return

    for key in _STREAMLIT_SECRET_KEYS:
        if os.environ.get(key):
            continue
        value = secrets.get(key)
        if value is None:
            nested = secrets.get("general")
            if isinstance(nested, dict):
                value = nested.get(key)
        if value:
            os.environ[key] = str(value)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openrouter_api_key: str = ""
    openrouter_vision_model: str = "google/gemini-3-pro-image-preview"
    openrouter_image_model: str = "google/gemini-3-pro-image-preview"
    tryon_api_key: str = ""
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    _apply_streamlit_secrets()
    return Settings()
