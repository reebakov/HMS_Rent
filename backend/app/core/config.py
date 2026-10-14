"""Все настройки приложения. Читаются из переменных окружения / файла .env."""
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]  # папка backend/


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings(BaseSettings):
    # .env ищется в корне проекта (локальный запуск из backend/) и рядом; в Docker переменные приходят из env_file
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), env_file_encoding="utf-8", extra="ignore")

    # --- Общее ---
    app_name: str = "HMS Rent"
    app_subtitle: str = "Аренда техники"  # подпись под названием в сайдбаре (APP_SUBTITLE в .env)
    environment: Literal["dev", "prod"] = "dev"
    public_url: str = "http://localhost:8080"  # адрес портала в браузере (из него собирается redirect URI для Microsoft)
    api_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:5173"
    display_timezone: str = "Europe/Moscow"

    # --- База данных ---
    database_url: str = "postgresql+asyncpg://hmsrent:hmsrent@localhost:5432/hmsrent"

    # --- Сессии ---
    secret_key: str = "change-me-please"
    session_ttl_hours: int = 12
    cookie_name: str = "hmsrent_session"
    cookie_secure: bool = False

    # --- Вход ---
    bouncer_authorize_url: str = ""
    bouncer_token_url: str = ""
    bouncer_client_id: str = ""
    bouncer_client_secret: str = ""
    admins_file: str = "config/admins.txt"
    auth_local_enabled: bool = True
    auth_dev_enabled: bool = False
    login_max_attempts: int = 5
    login_lock_minutes: int = 10

    # --- Jira / Insight ---
    insight_mode: Literal["mock", "live"] = "mock"
    jira_url: str = "https://jira.marvin-it.com"
    insight_token: str = ""  # Personal Access Token сервисной учётки (Bearer)
    insight_username: str = ""  # либо логин/пароль сервисной учётки (Basic); пусто — без авторизации
    insight_password: str = ""
    insight_verify_ssl: bool = True
    insight_api: Literal["iql", "aql"] = "iql"
    insight_page_size: int = 200
    insight_max_objects: int = 0  # 0 — без ограничения; >0 — пробная синхронизация первых N объектов
    insight_mapping_file: str = ""  # пусто — config/insight_mapping.yaml (live) или .mock.yaml (mock)
    insight_sync_interval_sec: int = 600
    insight_writeback: bool = False
    mock_data_file: str = "seed/mock_computers.json"

    # --- vSphere: виртуалки по запросу (конструктор в каталоге) ---
    vcenter_host: str = ""  # адрес vCenter — вписать в .env (VCENTER_HOST)
    vcenter_user: str = ""  # сервисная учётка, например svc-hmsrent@marvin-it.com
    vcenter_password: str = ""
    vcenter_verify_ssl: bool = False  # у внутреннего vCenter обычно самоподписанный сертификат
    vcenter_datacenter: str = "Godzen"
    vcenter_cluster: str = "Automat-GZ"
    vcenter_resource_pool: str = "Rent"  # vApp или пул ресурсов внутри кластера, куда кладём ВМ
    vcenter_folder: str = ""  # папка VMs and Templates (путь «A/B»); пусто — корень датацентра
    vcenter_template_windows: str = "Template_Win"  # шаблон, с которого клонируем
    vcenter_datastore: str = ""  # пусто — тот же datastore, что у шаблона
    vcenter_network: str = ""  # пусто — сеть как у шаблона
    vcenter_customization_spec: str = ""  # спецификация гостевой настройки (sysprep); пусто — без неё
    vm_name_prefix: str = "rent-"  # имя ВМ в vSphere = префикс + имя от пользователя

    # --- Категории мощности (если в Insight нет своего поля) ---
    tier_weak_min_ram_gb: int = 8  # слабее — в каталог не попадает (слабые = от 8 ГБ до границы «средних»)
    tier_medium_min_ram_gb: int = 15  # «15GB» в Insight — это 16 ГБ минус память под встройку
    tier_powerful_min_ram_gb: int = 32
    tier_medium_gpu: str = "1050,1060,1650,RX 5"
    tier_powerful_gpu: str = "RTX,1660,1070,1080,RX 6,RX 7,A4000,A5000"

    # --- Уведомления ---
    mattermost_webhook_url: str = ""

    # --- Справочник отделов по умолчанию (создаётся, если таблица пустая) ---
    default_departments: str = "Разработка,Тестирование (QA),Аналитика,Дизайн,Маркетинг,Поддержка"

    @property
    def bouncer_enabled(self) -> bool:
        return bool(self.bouncer_client_id and self.bouncer_client_secret and self.bouncer_authorize_url)

    @property
    def vsphere_configured(self) -> bool:
        return bool(self.vcenter_host and self.vcenter_user and self.vcenter_password)

    @property
    def microsoft_domains(self) -> list[str]:
        return [d.lower().lstrip("@") for d in _split(self.microsoft_allowed_domains)]

    @property
    def cors_list(self) -> list[str]:
        return _split(self.cors_origins)

    @property
    def medium_gpu_patterns(self) -> list[str]:
        return _split(self.tier_medium_gpu)

    @property
    def powerful_gpu_patterns(self) -> list[str]:
        return _split(self.tier_powerful_gpu)

    @property
    def default_department_list(self) -> list[str]:
        return _split(self.default_departments)

    @property
    def mapping_path(self) -> Path:
        name = self.insight_mapping_file or (
            "config/insight_mapping.mock.yaml" if self.insight_mode == "mock" else "config/insight_mapping.yaml"
        )
        return self.path(name)

    def path(self, relative: str) -> Path:
        p = Path(relative)
        return p if p.is_absolute() else BASE_DIR / p


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
