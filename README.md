# SIBSAU_BOT

**SIBSAU_BOT** — это Telegram-бот, разработанный для предоставления расписания студентов Сибирского государственного аэрокосмического университета (СИБГУ). Бот предлагает функционал для получения расписания.

## Содержание

- [Особенности](#особенности)
- [Требования](#требования)
- [Установка](#установка)
- [Конфигурация](#конфигурация)
- [Использование](#использование)
- [Структура проекта](#структура-проекта)
- [Команды](#команды)
- [Управление пользователями](#управление-пользователями)
- [Логирование и ошибки](#логирование-и-ошибки)
- [Лицензия](#лицензия)
- [Контакты](#контакты)

## Особенности

- **Текущее и завтрашнее расписание:** Получайте расписание на сегодня и завтра.
- **Недельное расписание:** Просматривайте расписание на 1-ю и 2-ю недели.
- **Расписание сессии:** Доступ к расписанию экзаменов.
- **Поиск:** Ищите конкретные предметы или преподавателей в расписании.
- **Управление пользователями:** Администраторы и модераторы могут управлять доступом пользователей.
- **Логирование и обработка ошибок:** Ведение логов и уведомление администратора о критических ошибках.
- **Статистика:** Администраторы могут просматривать статистику использования бота.

## Требования

- **Python 3.8+**
- **Git** (опционально, для клонирования репозитория)
- **Telegram Account**

## Установка

1. **Клонирование репозитория**

   ```bash
   git clone https://github.com/Baillora/SIBSAU_BOT.git
   cd SIBSAU_BOT

2. **Установка зависимостей**

Вы можете установить зависимости, используя предоставленный скрипт install.bat (для Windows) или вручную через pip.

## Конфигурация

1. **Настройка файла .env**

Создайте файл .env в корневой директории проекта и добавьте в него токен вашего Telegram-бота:

**TOKEN=YOUR_TELEGRAM_BOT_TOKEN_HERE**

**SCHEDULE_URL=URL_HERE**

**OWNER_ID=TELEGRAM_ID_HERE**

**PLAN_URL=SYLLABUS_URL (НЕ ОБЯЗАТЕЛЬНЫЙ)**

## Использование

1. **Использование start.bat (Windows):**

Дважды щелкните файл start.bat или выполните следующую команду в терминале:

start.bat

2. **Взаимодействие с ботом**

Откройте Telegram и найдите вашего бота по его имени пользователя.

Начните разговор, отправив команду /start.

Используйте доступные команды и кнопки для навигации по расписанию.

## Структура проекта

**.env:** Хранит переменные окружения, такие как токен бота.

**allowed_users.json:** Содержит список пользователей с доступом к боту и их роли.

**bot.py:** Основной Python-скрипт с логикой бота.

**install.bat:** Скрипт для установки зависимостей.

**requirements.txt:** Перечисляет необходимые Python-зависимости.

**start.bat:** Скрипт для запуска бота.

**warning.log:** Лог-файл для предупреждений и ошибок.

**stats.json** файл для сбора статистики.

## Команды

1. **Общедоступные команды**
   
**/start** — Запустить бота и показать главное меню.

**/help** — Показать доступные команды.

2. **Команды для авторизованных пользователей**
   
**/search <запрос>** — Поиск по предметам и преподавателям.

**/plan** — Показать учебный план.

3. **Команды для модераторов**
   
**/adduser <user_id>** — Добавить нового пользователя.

**/removeuser <user_id>** — Удалить существующего пользователя.

**/listusers** — Показать список всех авторизованных пользователей.

**/reload** — Перезагрузить кэш расписания.

4. **Команды только для администратора**

**/showlog [число_строк]** — Показать последние записи из логов.

**/stats** — Показать статистику использования бота.

**/mod <user_id>** — Назначить пользователя модератором.

**/unmod <user_id>** — Снять с пользователя роль модератора.

**/broadcast <сообщение> - Рассылка объявления**

5. **Команды только для овнера**

**/adm <user_id>** - Назначить пользователя администратором
  
**/unadm <user_id>** - Снять пользователя с роли администратора
  
**/restart** - Перезагрузить бота

## Управление пользователями

**Администраторы и модераторы могут управлять доступом пользователей к боту с помощью следующих команд:**

Добавление пользователя:

**/adduser <user_id>**

Удаление пользователя:

**/removeuser <user_id>**

Назначение модератора:

**/mod <user_id>**

Снятие роли модератора:

**/unmod <user_id>**

Просмотр списка пользователей:

**/listusers**

## Логирование и ошибки

**Логирование:** Бот ведет логирование в консоли и в файле warning.log. Предупреждения и ошибки записываются в warning.log.

**Обработка ошибок:** В случае возникновения ошибок бот уведомляет администратора через Telegram.

## Лицензия

Этот проект лицензирован под **MIT license**.

## Контакты

Если у вас есть вопросы или предложения, свяжитесь с разработчиком:

**Telegram:** @lssued
