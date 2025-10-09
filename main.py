# main.py
import sys
import os
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
    from scr.admin_panel.app import app, SSL_CERT, SSL_KEY
    
    cert_path = SSL_CERT if os.path.isabs(SSL_CERT) else os.path.join(os.getcwd(), SSL_CERT)
    key_path = SSL_KEY if os.path.isabs(SSL_KEY) else os.path.join(os.getcwd(), SSL_KEY)
    
    if os.path.exists(cert_path) and os.path.exists(key_path):
        ssl_context = (SSL_CERT, SSL_KEY)
        print("🔐 SSL включён. Панель будет доступна по HTTPS.")
    else:
        ssl_context = None
        print("⚠️ SSL-файлы не найдены. Панель будет работать по HTTP.")
    
    app.run(
        host="0.0.0.0",
        port=19999,
        ssl_context=ssl_context,
        use_reloader=False,
        debug=False
    )

if __name__ == "__main__":
    print_startup_messages()
    
    # Запускаем Flask в фоне
    flask_thread = threading.Thread(target=run_flask_in_thread, daemon=True)
    flask_thread.start()
    
    # Запускаем бота в основном потоке
    try:
        run_bot()
    except KeyboardInterrupt:
        print("\n🛑 Завершение работы...")