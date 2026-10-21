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
    app_version: str = "dev"  # версия сборки (sha коммита): задаёт образ при сборке в CI; по ней интерфейс замечает обновление
    app_subtitle: str = "Аренда техники"  # подпись под названием в сайдбаре (APP_SUBTITLE в .env)
    environment: Literal["dev", "prod"] = "dev"
    public_url: str = "http://localhost:8080"  # адрес портала в браузере (из него собирается redirect URI для Bouncer)
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
    bouncer_issuer: str = ""  # ожидаемый iss в id_token; пусто — не проверять
    admins_file: str = "config/admins.txt"
    work_calendar_file: str = "config/work_calendar.yaml"  # праздники и рабочие выходные для расчёта рабочих дней
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
    vcenter_customization_spec: str = ""  # спецификация гостевой настройки (sysprep); пусто — без неё

    # --- Категории мощности (если в Insight нет своего поля) ---
    tier_weak_min_ram_gb: int = 8  # слабее — в каталог не попадает (слабые = от 8 ГБ до границы «средних»)
    tier_medium_min_ram_gb: int = 15  # «15GB» в Insight — это 16 ГБ минус память под встройку
    tier_powerful_min_ram_gb: int = 32
    tier_medium_gpu: str = "1050,1060,1650,RX 5"
    tier_powerful_gpu: str = "RTX,1660,1070,1080,RX 6,RX 7,A4000,A5000"

    # --- Jira Service Desk: заявки «Сообщить о проблеме» и на возврат ПК (docs/SERVICE_DESK.md) ---
    sd_jira_url: str = "https://jira.getcom.pw"
    sd_token: str = ""  # Personal Access Token сервисной учётки (агент Service Desk)
    sd_username: str = ""  # или логин/пароль
    sd_password: str = ""
    sd_verify_ssl: bool = True
    sd_service_desk_id: int = 54  # из адреса портала …/desk/portal/54/…
    sd_request_type_problem: int = 1248  # «Проблема с ПК/ВМ»: …/portal/54/create/1248
    sd_request_type_return: int = 1252  # «Возврат ПК»: …/portal/54/create/1252
    sd_raise_on_behalf: bool = True  # создавать заявку от имени сотрудника (если он есть в Jira)
    sd_return_on_return: bool = True  # возврат ПК на сайте создаёт заявку «Возврат»
    sd_request_type_order: int = 1252  # «Прочее»: подготовка ПК после брони и сборка по запросу
    sd_prepare_on_booking: bool = True  # бронь ПК создаёт заявку «подготовить ПК» (ОС, первичная настройка)

    # --- Уведомления ---
    mattermost_webhook_url: str = ""  # канал исполнителей: бронь, возврат, ВМ, сводка просрочек
    # Почта заказчикам (по адресу из Bouncer): ВМ готова или не создана, срок заканчивается, срок закончился.
    # Выключена, пока не заданы smtp_host и smtp_from.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""  # пусто — без авторизации (внутренний relay)
    smtp_password: str = ""
    smtp_from: str = ""  # адрес отправителя, например hms-rent@deeplay.io
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"
    smtp_timeout: int = 15

    # --- Справочник отделов по умолчанию (создаётся, если таблица пустая) ---
    default_departments: str = "Разработка,Тестирование (QA),Аналитика,Дизайн,Маркетинг,Поддержка"

    @property
    def bouncer_enabled(self) -> bool:
        return bool(self.bouncer_client_id and self.bouncer_client_secret and self.bouncer_authorize_url)

    @property
    def service_desk_configured(self) -> bool:
        return bool(self.sd_jira_url and (self.sd_token or self.sd_username))

    @property
    def mail_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)

    @property
    def vsphere_configured(self) -> bool:
        return bool(self.vcenter_host and self.vcenter_user and self.vcenter_password)

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
