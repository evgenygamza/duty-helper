# Как запустить бота локально

На проде будет контейнер, это только для разработки.

## Запуск

```bash
cd ~/Projects/duty-helper/bot
set -a && . ~/.config/duty-helper/sandbox.env && set +a
.venv/bin/python app.py > /tmp/duty-bot.log 2>&1 &
```

Через несколько секунд в логе должно появиться `⚡️ Bolt app is running!`.

## Остановка и лог

```bash
pkill -f "app.py"          # остановить
pgrep -fl "app.py"         # проверить, жив ли
tail -f /tmp/duty-bot.log  # смотреть лог
```

Лог перезаписывается при каждом запуске — если нужен прошлый, копируй до старта.

## Что должно быть в окружении

`~/.config/duty-helper/sandbox.env`, права 600, в репозиторий не попадает:

```
SLACK_SANDBOX_TOKEN=xoxb-...       бот
SLACK_SANDBOX_APP_TOKEN=xapp-...   Socket Mode
SLACK_SANDBOX_USER_TOKEN=xoxp-...  поиск и чтение тредов
GEMINI_API_KEY=...                 модель
DUTY_GROUP_ID=S0BTF0KMJV6
DUTY_FEED_CHANNEL=C0BTQL7AK4K
DUTY_LIST_ID=F0BU23Y14PQ
```

Бот отказывается стартовать, если чего-то не хватает, и называет чего именно.

## Проверить, что живой

Тегнуть `@qa-factset-dutyman` в `#channel-with-bot` — через несколько секунд
в логе появится `item ... created`, на доске новая карточка.

Если модель отвалилась или упёрлась в квоту, бот напишет в `#duty-feed`
«не смог завести карточку» со ссылкой на тред. Пустой лог и тишина в канале
означают, что событие не дошло вовсе.

## Правка прав приложения

```bash
export PATH="$HOME/.local/bin:$PATH"
cd ~/Projects/duty-helper/bot
# поправить manifest.json, затем:
slack install --app local --team T0BSDLTDKBM --force
```

`--force` обязателен: без него CLI хочет подтверждения в интерактиве.
