#!/usr/bin/env bash
# Изолированная установка Mini App KRAFT. Ничего чужого не трогает.
set -euo pipefail

echo "=================================================================="
echo " ШАГ 0. ЧТО СЕЙЧАС РАБОТАЕТ НА СЕРВЕРЕ (проверка, ничего не меняем)"
echo "=================================================================="
echo "--- процессы ботов/python ---"
ps -eo pid,user,cmd | grep -iE 'bot|python|aiogram|telegram|node' | grep -v grep || echo "нет"
echo "--- systemd-сервисы пользователя/системы с 'bot' ---"
systemctl list-units --type=service --all 2>/dev/null | grep -iE 'bot|kraft|vin' || echo "нет"
echo "--- занятые порты ---"
(ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null) | grep LISTEN || true
echo
echo ">>> Убедитесь, что ВЫШЕ виден ваш @kraftVinComptabilityBot и он не будет затронут."
echo ">>> Мы поставим ОТДЕЛЬНЫЙ сервис kraft-miniapp на свободный порт. Enter — продолжить, Ctrl+C — отмена."
read -r _

# --- выбираем свободный порт из 8087/8090/8091 ---
PORT=""
for p in 8087 8090 8091 8093; do
  if ! (ss -tln 2>/dev/null || netstat -tln 2>/dev/null) | grep -q ":$p "; then PORT=$p; break; fi
done
[ -z "$PORT" ] && { echo "Все кандидаты-порты заняты, впишите свой в скрипт"; exit 1; }
echo "Свободный порт: $PORT"

APP=/opt/kraft-miniapp
sudo mkdir -p "$APP"
sudo chown "$USER":"$USER" "$APP"

echo "--- качаю Mini App из публичного репозитория ---"
BASE="https://marsmarcoss-cloud.github.io/marketing-ozon"
curl -fsSL "$BASE/index.html"   -o "$APP/index.html"
curl -fsSL "$BASE/catalog.json" -o "$APP/catalog.json"
echo "index.html: $(wc -c <"$APP/index.html") байт, catalog.json: $(($(wc -c <"$APP/catalog.json")/1024)) КБ"

# --- скрипт ежечасной подтяжки свежего каталога с Pages (цены обновляет GitHub Actions) ---
cat > "$APP/pull.sh" <<PULL
#!/usr/bin/env bash
set -e
curl -fsSL "$BASE/catalog.json" -o "$APP/catalog.json.tmp" && mv "$APP/catalog.json.tmp" "$APP/catalog.json"
PULL
chmod +x "$APP/pull.sh"

echo "--- создаю ОТДЕЛЬНЫЙ systemd-сервис kraft-miniapp (порт $PORT) ---"
sudo tee /etc/systemd/system/kraft-miniapp.service >/dev/null <<UNIT
[Unit]
Description=KRAFT Mini App (static catalog)
After=network.target

[Service]
Type=simple
WorkingDirectory=$APP
ExecStart=/usr/bin/python3 -m http.server $PORT --bind 127.0.0.1
Restart=always
User=$USER

[Install]
WantedBy=multi-user.target
UNIT

# --- таймер подтяжки каталога раз в час ---
sudo tee /etc/systemd/system/kraft-miniapp-pull.service >/dev/null <<UNIT
[Unit]
Description=KRAFT Mini App catalog pull
[Service]
Type=oneshot
ExecStart=$APP/pull.sh
User=$USER
UNIT
sudo tee /etc/systemd/system/kraft-miniapp-pull.timer >/dev/null <<UNIT
[Unit]
Description=KRAFT Mini App catalog pull hourly
[Timer]
OnCalendar=*:12
Persistent=true
[Install]
WantedBy=timers.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now kraft-miniapp.service
sudo systemctl enable --now kraft-miniapp-pull.timer

echo
echo "=================================================================="
echo " ГОТОВО. Mini App работает локально: http://127.0.0.1:$PORT"
echo " Сервис:  sudo systemctl status kraft-miniapp   (только наш, чужого не трогали)"
echo "=================================================================="
echo "--- контрольная проверка: чужой бот жив? ---"
ps -eo pid,user,cmd | grep -iE 'vin|comptab' | grep -v grep || echo "(процесс VIN-бота ищите по своему имени — он НЕ перезапускался)"
curl -fsS "http://127.0.0.1:$PORT/catalog.json" | head -c 60; echo " ... каталог отдаётся ✅"
