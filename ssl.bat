@echo off
setlocal
chcp 65001 > nul

:: Проверка наличия OpenSSL
where openssl >nul 2>nul
if errorlevel 1 (
    echo Ошибка: OpenSSL не установлен!
    echo Установите OpenSSL и добавьте его в PATH
    pause
    exit /b 1
)

set SSL_DIR=%~dp0ssl
if not exist "%SSL_DIR%" mkdir "%SSL_DIR%"

openssl req -x509 -nodes -days 3650 -newkey rsa:2048 ^
  -keyout "%SSL_DIR%\self_signed.key" ^
  -out "%SSL_DIR%\self_signed.crt" ^
  -subj "/C=RU/ST=Local/L=Local/O=MyBot/CN=localhost"

if errorlevel 1 (
    echo Ошибка при генерации сертификата!
    pause
    exit /b 1
)

echo ============================================================
echo    Установка завершена, ключи сгенерированы!
echo ============================================================
echo Сертификат и ключ (на 10 лет) сгенерированы в %SSL_DIR%
echo.
echo Для .env используйте:
echo SSL_CERT=%SSL_DIR%\self_signed.crt
echo SSL_KEY=%SSL_DIR%\self_signed.key
echo.
echo ============================================================

chcp 866 > nul
pause