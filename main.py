# main.py
import sys
import os
import time
import threading
from pystyle import Colorate, Colors, Center

sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from scr.bot.bot_app import run_bot


def print_startup_messages():
    ascii_art = """
      :::::::::           :::        :::::::::::       :::        :::        ::::::::       :::::::::           :::
     :+:    :+:        :+: :+:          :+:           :+:        :+:       :+:    :+:      :+:    :+:        :+: :+:
    +:+    +:+       +:+   +:+         +:+           +:+        +:+       +:+    +:+      +:+    +:+       +:+   +:+
   +#++:++#+       +#++:++#++:        +#+           +#+        +#+       +#+    +:+      +#++:++#:       +#++:++#++:
  +#+    +#+      +#+     +#+        +#+           +#+        +#+       +#+    +#+      +#+    +#+      +#+     +#+
 #+#    #+#      #+#     #+#        #+#           #+#        #+#       #+#    #+#      #+#    #+#      #+#     #+#
#########       ###     ###    ###########       ########## ########## ########       ###    ###      ###     ###
    
                Improvements can be made to the code. If you're getting an error, visit my tg.
                                    Github: https://github.com/Baillora  
                                       Telegram: https://t.me/lssued  
    """
    print(Colorate.Vertical(Colors.red_to_yellow, Center.XCenter(ascii_art)))


def run_flask_in_thread():
    from scr.admin_panel.app import app
    from scr.core.settings import SSL_CERT, SSL_KEY
    
    cert_path = SSL_CERT if os.path.isabs(SSL_CERT) else os.path.join(os.getcwd(), SSL_CERT)
    key_path = SSL_KEY if os.path.isabs(SSL_KEY) else os.path.join(os.getcwd(), SSL_KEY)
    
    if os.path.exists(cert_path) and os.path.exists(key_path):
        ssl_context = (cert_path, key_path)
        print("🔐 SSL включён. Панель доступна по HTTPS: https://127.0.0.1:19999")
    else:
        ssl_context = None
        print("🌐 Панель управления запущена: http://127.0.0.1:19999 (или http://localhost:19999)")
    
    try:
        app.run(
            host="0.0.0.0",
            port=19999,
            ssl_context=ssl_context,
            use_reloader=False,
            debug=False
        )
    except Exception as e:
        print(f"❌ Ошибка запуска веб-панели: {e}")


if __name__ == "__main__":
    print_startup_messages()
    
    # Запускаем Flask в фоновом потоке
    flask_thread = threading.Thread(target=run_flask_in_thread, daemon=True)
    flask_thread.start()
    
    # Запускаем бота в основном потоке с защитой от сетевых сбоев
    while True:
        try:
            run_bot()
            break
        except KeyboardInterrupt:
            print("\n🛑 Завершение работы...")
            break
        except Exception as e:
            print(f"⚠️ Сетевой сбой или перезапуск бота: {e}. Повторное подключение через 5 секунд...")
            time.sleep(5)