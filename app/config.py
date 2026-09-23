"""Конфигурация приложения."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings

from app import __version__


class Settings(BaseSettings):
    """Настройки приложения из переменных окружения."""

    app_name: str = "pd-proxy"
    version: str = __version__
    host: str = "0.0.0.0"
    port: int = 8080
    workers: int = 1
    log_level: str = "info"

    # Аутентификация
    auth_enabled: bool = False

    # Хранилище маппингов
    storage_ttl_seconds: int = 3600  # 1 час
    storage_max_size: int = 100_000

    # LLM-прокси (AlfaGen) — фоллбэк / альтернатива
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "deepseek-ai/DeepSeek-V4-Flash-0731"

    # FastJev (Эшелон 2 — локальный классификатор)
    jev_enabled: bool = True
    jev_model: str = "Qwen/Qwen3-0.6B"
    jev_revision: str = "c1899de289a04d12100db370d81485cdf75e47ca"
    jev_max_input_tokens: int = 4096
    jev_confidence_threshold: float = 0.6

    # Логирование
    log_file: str = ""  # PD_PROXY_LOG_FILE — путь к файлу логов (пустой = только stdout)
    log_file_max_mb: int = 50  # Размер ротации (МБ)
    log_file_backup_count: int = 5  # Кол-во ротируемых файлов

    # Пути
    systems_config_path: str = "config/systems.yaml"

    model_config = {"env_prefix": "PD_PROXY_"}


# Кэш конфигурации систем
_systems_config_cache: dict | None = None
_systems_config_mtime: float = 0.0


def load_systems_config(path: str | None = None) -> dict:
    """Загрузить конфигурацию систем из YAML (с кэшированием по mtime)."""
    global _systems_config_cache, _systems_config_mtime
    if path is None:
        path = settings.systems_config_path
    config_path = Path(path)
    if not config_path.exists():
        return {"systems": {}}
    try:
        mtime = config_path.stat().st_mtime
    except OSError:
        return {"systems": {}}
    if _systems_config_cache is not None and mtime == _systems_config_mtime:
        return _systems_config_cache
    with open(config_path, encoding="utf-8") as f:
        _systems_config_cache = yaml.safe_load(f) or {"systems": {}}
    _systems_config_mtime = mtime
    return _systems_config_cache


def save_systems_config(config: dict, path: str | None = None) -> None:
    """Сохранить конфигурацию систем в YAML (с бэкапом и сбросом кэша)."""
    global _systems_config_cache, _systems_config_mtime
    if path is None:
        path = settings.systems_config_path
    config_path = Path(path)
    # Бэкап перед перезаписью
    if config_path.exists():
        backup_path = config_path.with_suffix(".yaml.bak")
        import shutil
        shutil.copy2(config_path, backup_path)
    # Записываем YAML
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(
            config,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )
    # Сброс кэша — следующий load подхватит новый файл
    _systems_config_cache = None
    _systems_config_mtime = 0.0


settings = Settings()
