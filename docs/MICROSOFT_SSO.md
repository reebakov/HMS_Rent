# Вход сотрудников через рабочие учётки Microsoft (Entra ID)

Сотрудник нажимает «Войти через Microsoft», выбирает рабочую учётную запись — и он в портале. Пароли портал
не хранит. Используется стандартный протокол OpenID Connect (authorization code flow) с Microsoft Entra ID
(бывший Azure AD).

## Что нужно для подключения — коротко

Всё это делает администратор Microsoft 365 / Entra ID вашей организации (роль *Application Administrator* или
выше), ~15 минут. От него вам нужны **три значения** и одно подтверждение:

| Что получить | Куда вписать | Где взять в Entra ID |
|---|---|---|
| **Directory (tenant) ID** — GUID организации | `MICROSOFT_TENANT_ID` | App registration → Overview |
| **Application (client) ID** — GUID приложения | `MICROSOFT_CLIENT_ID` | App registration → Overview |
| **Client secret (Value)** — значение секрета | `MICROSOFT_CLIENT_SECRET` | Certificates & secrets → New client secret |
| Подтверждение, что *admin consent* не требуется (или выдан) | — | см. п. 4 ниже |

Со стороны портала нужен **https-адрес с доменным именем** (например `hmsrent.<ваш-домен>`): Microsoft разрешает
`http://` в redirect URI только для `localhost`. Адрес может резолвиться только внутри сети — главное, чтобы
браузер сотрудника его открывал и сертификат был доверенным.

## 1. Регистрация приложения в Entra ID

1. https://entra.microsoft.com → **Identity → Applications → App registrations → New registration**.
2. **Name** — `HMS Rent`.
3. **Supported account types** — **Accounts in this organizational directory only (Single tenant)**.
   Это ключевая настройка: войти смогут только учётки вашей организации.
4. **Redirect URI** — платформа **Web**:
   * `https://hmsrent.<ваш-домен>/api/v1/auth/microsoft/callback` — для виртуалки;
   * `http://localhost:8080/api/v1/auth/microsoft/callback` — для локального запуска (можно добавить вторым).
   При запуске фронтенда через `npm run dev` это `http://localhost:5173/api/v1/auth/microsoft/callback`.
5. **Register**. На странице **Overview** скопируйте *Application (client) ID* и *Directory (tenant) ID*.

## 2. Клиентский секрет

**Certificates & secrets → Client secrets → New client secret**. Скопируйте столбец **Value** сразу — потом
он больше не показывается (нужен именно *Value*, а не *Secret ID*).

> ⚠️ У секрета есть срок действия (максимум 24 месяца). Поставьте напоминание в календарь: когда секрет
> истечёт, вход через Microsoft перестанет работать, пока не будет выпущен новый и обновлён `.env`.

## 3. Токен: какие данные приходят

**Token configuration → Add optional claim → ID** — добавьте **`email`** и **`upn`**. Портал берёт логин сотрудника
из `email`, а если его нет — из `preferred_username` (UPN). Так что без этой настройки вход тоже работает,
но с ней логин всегда будет рабочей почтой. Если Entra предложит «Turn on the Microsoft Graph email permission» —
согласитесь.

## 4. Разрешения (API permissions)

Нужны только стандартные делегированные права **Microsoft Graph → `openid`, `profile`, `email`** (и `User.Read`,
он добавляется автоматически). Они не требуют согласия администратора в большинстве организаций. Если в вашем tenant
пользователям запрещено соглашаться на доступ к приложениям, нажмите **Grant admin consent for <организация>**
на странице API permissions.

## 5. Кто именно сможет войти (рекомендуется)

По умолчанию войти может любой пользователь вашего tenant. Чтобы ограничить круг людей:

* **Enterprise applications → HMS Rent → Properties → Assignment required? = Yes**;
* **Users and groups → Add user/group** — добавьте нужную группу (например, `HMS-Rent-Users`).

Остальные при попытке входа получат ошибку от Microsoft. Дополнительно портал может проверять домен почты
(`MICROSOFT_ALLOWED_DOMAINS`, см. ниже) и сам разделяет роли: администраторы — по списку почт.

## 6. `.env`

```env
PUBLIC_URL=https://hmsrent.<ваш-домен>
MICROSOFT_TENANT_ID=00000000-0000-0000-0000-000000000000
MICROSOFT_CLIENT_ID=00000000-0000-0000-0000-000000000000
MICROSOFT_CLIENT_SECRET=<Value секрета>
# необязательно: пускать только почту этих доменов (через запятую); пусто — любой пользователь tenant
MICROSOFT_ALLOWED_DOMAINS=
COOKIE_SECURE=true
```

`PUBLIC_URL` должен совпадать с адресом, по которому открывают портал, — из него собирается redirect URI, и он
должен **буква в букву** совпасть с тем, что записан в Entra ID (схема, домен, путь). После правки `.env`:
`docker compose up -d --force-recreate backend worker`.

Проверка: на странице входа должна появиться кнопка «Войти через Microsoft». В логе backend при старте
не должно быть предупреждения «Вход через Microsoft выключен».

## 7. Администраторы

Два варианта, можно совмещать:

| Вариант | Как | Плюсы |
|---|---|---|
| **Через Microsoft** (основной) | рабочая почта в `backend/config/admins.txt`, по одной в строке | личные учётки: в журнале видно, кто из админов что сделал; файл перечитывается на лету — добавили/убрали почту, и права меняются без перезапуска |
| **Локальная учётка** | `docker compose exec backend python -m app.cli create-admin <логин> --name "Имя"` — пароль вводится в консоли | работает, даже если Microsoft недоступен; удобно как «аварийный» вход |

Почта в `admins.txt` должна совпадать с почтой (или UPN) рабочей учётки Microsoft — сравнение без учёта регистра.
Локальные учётки: `set-password <логин>`, `disable <логин>`, `users` — список всех.
Форма входа для них — «Вход для администраторов» на странице входа (`AUTH_LOCAL_ENABLED=true`).
После 5 неудачных попыток логин блокируется на 10 минут.

## Типичные ошибки

| Сообщение | Причина |
|---|---|
| `AADSTS50011: The redirect URI ... does not match` | redirect URI в Entra ID не совпадает с `PUBLIC_URL` + `/api/v1/auth/microsoft/callback` |
| `AADSTS700016: Application not found in the directory` | неверный `MICROSOFT_CLIENT_ID` или `MICROSOFT_TENANT_ID` |
| `AADSTS7000215: Invalid client secret` | в `.env` попал *Secret ID* вместо *Value* или секрет истёк |
| `AADSTS50105` / `AADSTS65001` | пользователь не назначен на приложение (п. 5) или нужен admin consent (п. 4) |
| «Вход разрешён только с рабочей учётной записи организации» | токен выдан другим tenant — проверьте `MICROSOFT_TENANT_ID` |
| «Вход разрешён только с рабочей почты (...)» | домен почты не входит в `MICROSOFT_ALLOWED_DOMAINS` |

Фото профиля Microsoft в токене не передаёт, поэтому в портале показываются инициалы.
