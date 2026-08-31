#!/usr/bin/env bash
# ==========================================================
# Скрипт автоматической установки и настройки SIBSAU_BOT
# для Ubuntu / Debian Linux Server
# ==========================================================

set -e

echo "=========================================================="
echo "🚀 Начало настройки SIBSAU_BOT на Ubuntu Server..."
echo "=========================================================="

# 1. Проверка прав (если root или с sudo)
CURRENT_DIR=$(pwd)
APP_USER=$(whoami)

echo "📂 Рабочая директория: $CURRENT_DIR"
echo "👤 Пользователь: $APP_USER"

# 2. Обновление пакетов и установка Python + venv + pip
echo "📦 Установка системных зависимостей (Python 3, pip, venv)..."
if [ "$APP_USER" = "root" ]; then
    apt update -y && apt install -y python3 python3-pip python3-venv git
else
    sudo apt update -y && sudo apt install -y python3 python3-pip python3-venv git
fi

# 3. Создание и активация виртуального окружения
if [ ! -d "venv" ]; then
    echo "🐍 Создание виртуального окружения venv..."
    python3 -m venv venv
fi

echo "📥 Установка Python-зависимостей из requirements.txt..."
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

# 4. Проверка наличия .env файла
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo "⚠️ Файл .env не найден! Создаю из .env.example..."
        cp .env.example .env
        echo "❗ Пожалуйста, заполните .env вашими данными (токен, пароли)."
    fi
fi

# 5. Создание systemd сервиса для автозапуска в фоне
SERVICE_FILE="/etc/systemd/system/sibsau_bot.service"
echo "⚙️ Настройка службы systemd ($SERVICE_FILE)..."

SERVICE_CONTENT="[Unit]
Description=SIBSAU Telegram Bot & Flask Admin Panel
After=network.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$CURRENT_DIR
ExecStart=$CURRENT_DIR/venv/bin/python main.py
Restart=always
RestartSec=5
EnvironmentFile=$CURRENT_DIR/.env

[Install]
WantedBy=multi-user.target"

if [ "$APP_USER" = "root" ]; then
    echo "$SERVICE_CONTENT" > $SERVICE_FILE
    systemctl daemon-reload
    systemctl enable sibsau_bot
    systemctl restart sibsau_bot
else
    echo "$SERVICE_CONTENT" | sudo tee $SERVICE_FILE > /dev/null
    sudo systemctl daemon-reload
    sudo systemctl enable sibsau_bot
    sudo systemctl restart sibsau_bot
fi

echo "=========================================================="
echo "✅ Бот успешно настроен и запущен в фоне через systemd!"
echo "=========================================================="
echo "🔍 Команды управления:"
echo "   sudo systemctl status sibsau_bot   # Проверить статус"
echo "   sudo systemctl restart sibsau_bot  # Перезапустить"
echo "   sudo systemctl stop sibsau_bot     # Остановить"
echo "   sudo journalctl -u sibsau_bot -f   # Смотреть живые логи"
echo "=========================================================="
