# 🤖 SIBSAU_BOT — Telegram-бот и Веб-панель СибГУ им. М.Ф. Решетнёва

[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](https://www.python.org/)
[![Telegram Bot API](https://img.shields.io/badge/Telegram%20Bot%20API-v21.10-blue.svg)](https://python-telegram-bot.org/)
[![Flask](https://img.shields.io/badge/Flask-3.0%2B-green.svg)](https://flask.palletsprojects.com/)
[![Tests](https://img.shields.io/badge/Tests-79%20passed-brightgreen.svg)](https://pytest.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

**SIBSAU_BOT** — это многофункциональный Telegram-бот и защищенная веб-панель управления с ролевой моделью доступа (RBAC), разработанные для студентов и преподавателей Сибирского государственного университета науки и технологий им. М.Ф. Решетнёва.

---

## 🌟 Основные возможности

### 🎓 Для студентов и пользователей:
- 📅 **Расписание на сегодня, завтра и всю неделю:** Четкое разделение пар по числителю/знаменателю с автоматическим расчетом четности семестра.
- ⏳ **Live-статус пары в реальном времени:** Отображение текущего занятия, графического прогресс-бара `[██████░░░░] 60%`, времени до звонка и следующей пары.
- 👥 **Фильтрация по подгруппам:** Персональное переключение между 1-й, 2-й подгруппой или общим расписанием (`/subgroup`).
- 📥 **Экспорт в Календарь (.ics):** Мгновенная генерация файла iCalendar на весь семестр с возможностью импорта в Google Calendar, Apple Calendar и Яндекс.Календарь (`/export`).
- 🔔 **Утренний дайджест:** Автоматическая утренняя рассылка расписания в **07:30** по красноярскому времени (`Asia/Krasnoyarsk`, UTC+7) (`/notifications`).
- 📝 **Личные заметки и дедлайны:** Привязка заметок и домашних заданий к конкретным предметам (`/note`, `/notes`, `/delnote`).
- 🏛 **Справочник аудиторий и корпусов:** Интерактивный справочник корпусов («Л», «Н», «А», «К» и др.), подсказки по переходам и карта (`/room`, `/map`, `/plan`).
- 🔍 **Умный поиск и Inline-режим:** Поиск по предметам, кабинетам и преподавателям как внутри бота (`/search`), так и в любых чатах через `@имя_бота <запрос>`.

---

### 🌐 Веб-панель и безопасность:
- 🔑 **Вход через Telegram в 1 клик:** Получение одноразовой ссылки авторизации и 6-значного OTP-кода через команду `/web`.
- 🛡️ **Строгая ролевая модель доступа (RBAC):**
  - `Студент (user)` — просмотр расписания в браузере.
  - `Модератор (mod)` — расписание, список пользователей, добавление/удаление студентов, обновление кэша.
  - `Администратор (admin)` — статистика, логи, рассылка, управление модераторами и студентами, личные сообщения.
  - `Владелец (owner)` — полный доступ, системные настройки, SSL-конфигурация, смена ролей, очистка логов и перезапуск.
- 🌐 **Динамическое управление доменом:** Команда `/setpanel <url>` в боте для быстрой настройки внешнего IP, DDNS или домена.
- 🔒 **Шифрование SSL/HTTPS:** Поддержка самоподписанных сертификатов и сертификатов Let's Encrypt / CA с автоматическим поиском путей.
- ☑️ **Сессии «Запомнить меня»:** Сохранение сессии авторизации на 30 дней в защищенных cookies (`HttpOnly`, `SameSite=Strict`).
- 🛡️ **Защита информации (InfoSec):** OWASP-заголовки (CSP, HSTS, X-Frame-Options), Rate Limiting против перебора, защита от SSRF/XSS и мгновенные алерты Владельцу о попытках входа.
- 🌐 **Поддержка Proxy:** Работа через HTTP, SOCKS5 или локальный VLESS / Xray Reality прокси.

---

## 📂 Структура репозитория

```text
SIBSAU_BOT/
├── scr/
│   ├── bot/                   # Telegram-бот
│   │   ├── handlers/          # Обработчики команд и callback-кнопок
│   │   │   ├── admin.py       # Админ-команды (/adduser, /stats, /setpanel и др.)
│   │   │   ├── calendar_export.py # Генерация .ics файлов
│   │   │   ├── inline.py      # Inline-поиск в любых чатах
│   │   │   ├── misc.py        # /help, /notes, /search, /room, /notifications
│   │   │   ├── schedule.py    # Просмотр расписания и навигация по дням
│   │   │   ├── start.py       # Главное меню и live-виджеты
│   │   │   ├── teachers.py    # Поиск преподавателей и консультаций
│   │   │   ├── utils.py       # Декораторы прав, форматирование, прогресс-бар
│   │   │   └── web_auth.py    # Обработчик команды /web
│   │   └── bot_app.py         # Инициализация PTB и планировщика задач
│   ├── core/                  # Системное ядро
│   │   ├── auth_tokens.py     # Менеджер OTP-кодов и токенов веб-панели
│   │   ├── logger.py          # Логирование с ротацией и маскированием токенов
│   │   ├── notes.py           # Потокобезопасное хранилище заметок (notes.json)
│   │   ├── settings.py        # Конфигурация, таймзоны и автоопределение IP
│   │   ├── stats.py           # Потокобезопасная аналитика (stats.json)
│   │   └── users.py           # Управление ролями и доступом (allowed_users.json)
│   ├── parsers/               # Парсеры портала АСУ Паллада СибГУ
│   │   ├── schedule_parser.py # Парсер расписания и сессии
│   │   └── teacher_parser.py  # Парсер преподавателей
│   └── admin_panel/           # Веб-панель управления (Flask)
│       ├── app.py             # Сервер Flask, маршруты и RBAC
│       ├── forms.py           # Формы WTForms
│       ├── static/            # Статические ресурсы
│       └── templates/         # Jinja2 шаблоны (Bootstrap 5, темная тема)
├── ssl/                       # Директория для SSL-сертификатов
├── tests/                     # Автоматические тесты (pytest)
├── .env.example               # Шаблон файла конфигурации
├── pytest.ini                 # Настройки запуска тестов
├── requirements.txt           # Список зависимостей Python
├── RELEASE_NOTES.md           # История версий и релизов
└── main.py                    # Главная точка входа (Бот + Веб-панель)
```

---

## 🚀 Быстрый старт

### 1. Клонирование репозитория
```bash
git clone https://github.com/Baillora/SIBSAU_BOT.git
cd SIBSAU_BOT
```

### 2. Создание виртуального окружения и установка зависимостей
```bash
python3 -m venv venv
source venv/bin/activate   # На Linux/macOS
# venv\Scripts\activate    # На Windows

pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Настройка конфигурации (`.env`)
Скопируйте пример файла конфигурации:
```bash
cp .env.example .env
nano .env
```

Заполните основные параметры:
```ini
TOKEN=1234567890:ABCdefGhIjkLmNoPqRsTuVwXyZ       # Токен от @BotFather
OWNER_ID=1651557527                                # Ваш Telegram ID
SCHEDULE_URL=https://timetable.pallada.sibsau.ru/timetable/group/13974
PANEL_USER=admin
PANEL_PASS=YourStrongPassword123!
FLASK_SECRET=your_super_secret_random_key
```

### 4. Генерация SSL-сертификатов (опционально, для HTTPS)
Для генерации бесплатного самоподписанного сертификата выполните:
```bash
mkdir -p ssl
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout ssl/self_signed.key \
  -out ssl/self_signed.crt \
  -subj "/C=RU/ST=Krasnoyarsk/L=Krasnoyarsk/O=SIBSAU/CN=localhost"
```

### 5. Запуск
```bash
python main.py
```
- Бот начнет опрос обновлений Telegram.
- Веб-панель станет доступна по адресу: `http://localhost:19999` (или `https://` при включенном SSL).

---

## 🐧 Развертывание на сервере Ubuntu (systemd)

Для автономной работы бота 24/7 в фоновом режиме создайте systemd-сервис:

```bash
sudo nano /etc/systemd/system/sibsau_bot.service
```

Вставьте конфигурацию (замените `baillora` на имя вашего пользователя):
```ini
[Unit]
Description=SIBSAU Telegram Bot & Flask Admin Panel
After=network.target

[Service]
Type=simple
User=baillora
WorkingDirectory=/home/baillora/sibsau_bot
ExecStart=/home/baillora/sibsau_bot/venv/bin/python main.py
Restart=always
RestartSec=5
StandardOutput=append:/home/baillora/sibsau_bot/warning.log
StandardError=append:/home/baillora/sibsau_bot/warning.log

[Install]
WantedBy=multi-user.target
```

Активируйте и запустите службу:
```bash
sudo systemctl daemon-reload
sudo systemctl enable sibsau_bot
sudo systemctl start sibsau_bot
```

Проверка статуса и просмотр логов:
```bash
sudo systemctl status sibsau_bot
sudo journalctl -u sibsau_bot -f
```

---

## 💬 Команды Telegram-бота

### 🤖 Общие команды
| Команда | Описание |
| :--- | :--- |
| `/start` | Главное меню, виджет текущей пары и кнопки навигации |
| `/help` | Подробная справка по всем командам в зависимости от ранга |
| `/web` | Получение 1-клик ссылки и 6-значного OTP-кода для входа в веб-панель |

### 📚 Для студентов (`user`)
| Команда | Описание |
| :--- | :--- |
| `/search <запрос>` | Умный поиск по предметам, кабинетам и преподавателям |
| `/subgroup [1\|2\|all]` | Выбор своей учебной подгруппы (1 / 2) |
| `/export` | Скачать файл расписания `.ics` для Google/Apple/Яндекс Календаря |
| `/notifications` | Включить или выключить утренние напоминания (07:30) |
| `/note <предмет> : <текст>` | Добавить личную заметку или дедлайн к предмету |
| `/notes` | Список всех сохраненных заметок |
| `/delnote <id>` | Удалить заметку по её ID |
| `/room <номер/корпус>` | Справочник аудиторий, корпусов и переходов |
| `/plan` | Ссылка на учебный план группы |
| `/map` | Интерактивная карта корпусов университета |

### 👮 Для модераторов (`mod`)
| Команда | Описание |
| :--- | :--- |
| `/adduser <user_id>` | Предоставить пользователю доступ к боту (роль `user`) |
| `/removeuser <user_id>` | Отозвать доступ у пользователя |
| `/listusers` | Просмотр списка авторизованных пользователей |
| `/reload` | Сбросить и обновить кэш расписания |

### 🛡️ Для администраторов (`admin`)
| Команда | Описание |
| :--- | :--- |
| `/fullreload` | Полная перезагрузка (расписание + преподаватели) |
| `/showlog [n]` | Просмотр последних $n$ строк системного журнала логов |
| `/stats` | Подробная статистика использования и активности бота |
| `/mod <user_id>` | Назначить пользователя модератором |
| `/unmod <user_id>` | Снять пользователя с роли модератора |
| `/broadcast <текст>` | Отправить рассылку-объявление всем пользователям |

### 👑 Для владельца (`owner`)
| Команда | Описание |
| :--- | :--- |
| `/adm <user_id>` | Назначить пользователя администратором |
| `/unadm <user_id>` | Снять пользователя с роли администратора |
| `/setpanel [url\|auto]` | Настроить домен/DDNS/IP веб-панели для генерации ссылок |
| `/restart` | Безопасный перезапуск процесса бота |

---

## 🛡️ Ролевая модель веб-панели (RBAC Matrix)

| Раздел веб-панели | Студент (`user`) | Модератор (`mod`) | Админ (`admin`) | Владелец (`owner`) |
| :--- | :---: | :---: | :---: | :---: |
| 📅 **Расписание (`/schedule`)** | ✅ | ✅ | ✅ | ✅ |
| 👥 **Список пользователей (`/users`)** | ❌ | ✅ *(только user)* | ✅ *(user и mod)* | ✅ *(все роли)* |
| 📩 **Личные сообщения из панели** | ❌ | ❌ | ✅ | ✅ |
| 📊 **Статистика и графики (`/`)** | ❌ | ❌ | ✅ | ✅ |
| 📜 **Просмотр и скачивание логов (`/logs`)**| ❌ | ❌ | ✅ | ✅ |
| 🗑️ **Очистка файла логов** | ❌ | ❌ | ❌ | ✅ |
| ⚡️ **Общая рассылка (`/control`)** | ❌ | ❌ | ✅ | ✅ |
| ⚙️ **Системные настройки и SSL (`/settings_panel`)** | ❌ | ❌ | ❌ | ✅ |
| 🔑 **Сброс 2FA аутентификации** | ❌ | ❌ | ❌ | ✅ |

---

## 🧪 Автоматическое тестирование

Проект полностью протестирован с помощью `pytest` и `pytest-asyncio`:

```bash
pytest -v
```

```text
============================= test session starts =============================
collected 69 items

tests/test_admin_panel.py ........                                       [ 11%]
tests/test_core.py ...                                                   [ 15%]
tests/test_handlers_admin.py .......                                     [ 26%]
tests/test_handlers_commands.py .....                                    [ 33%]
tests/test_handlers_schedule.py ...                                      [ 37%]
tests/test_handlers_teachers.py ..                                       [ 40%]
tests/test_logger.py .                                                   [ 42%]
tests/test_new_features.py ......                                        [ 50%]
tests/test_notes_and_panel.py .......                                    [ 60%]
tests/test_parsers.py .....                                              [ 68%]
tests/test_real_html.py .                                                [ 69%]
tests/test_security.py ......                                            [ 78%]
tests/test_telegram_auth_rbac.py ...............                         [100%]

======================= 69 passed, 1 warning in 15.97s ========================
```

---

## 👨‍💻 Автор и поддержка
- Разработчик: [@m3di4](https://t.me/m3di4)
- GitHub: [Baillora/SIBSAU_BOT](https://github.com/Baillora/SIBSAU_BOT)

---

## 📜 Лицензия
Данный проект лицензирован на условиях [MIT License](./LICENSE).
