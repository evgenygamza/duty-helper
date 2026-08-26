# Известные повторяющиеся инциденты

Каталог паттернов, которые уже случались. Если симптом совпал — это не новьё,
смотри порядок восстановления и линкуй к существующим ITSM, новый тикет не заводи.

---

## 1. FactSet DROP TABLE → fds-loader → каскад на snapshots

**Класс:** провайдерский. FactSet периодически (часто по выходным) выкатывает
новый `DROP TABLE` — пересоздаёт FDS-таблицы `fds.ff_v3_*`. Наш fds-loader не
может дропнуть старые, потому что на них висят зависимые объекты (в т.ч. **dbt
views** — новое осложнение), и загрузка встаёт. Дальше каскад на snapshots.

**Симптомы (алерты/логи):**
- `cannot drop table fds.ff_v3_* because other objects depend on it` (fds-loader)
- `too many failed DB queries` на hub{3,4}-factset-snapshots
- дедлоки: `deadlock detected (SQLSTATE 40P01)` на `tv.get_balance_sheet` и др.
- `bond publish blocked` / `entity publish blocked` / `entity failed`
- `relation "dbt_snapshots.mart_snapshots__<X>" does not exist (SQLSTATE 42P01)`
- factset-loader unhealthy / не стартует; healthcheck 403

**Порядок восстановления (плейбук Kirill/Ivan):**
1. стоп сервисов factset
2. скатить **dbt views** (иначе блокируют DROP таблиц поставщиком) — до скатки tv
3. (staging) удалить персональные схемы разработчиков — мешают скату миграций
4. скатить миграции `tv` + нужные `fds` (осторожно: `migrations rollback-all tv`,
   `migrations rollback-all fds --table=<список>`; некоторые накатывают объёмные индексы)
5. дать fds-loader отработать (может идти ~8 часов)
6. накатить всё обратно
- Для stable/prod всю последовательность делает план Jenkins
  `Product/Data Integration/Factset/deploy`.

**Кого звать:** `@factset-dev` (обычно Ivan Grigorev, Kirill Adamuk). Работы на
проде — через ITSM-тикеты redeploy с апрувом.

**Примеры тикетов (июль 2026):** ITSM-71355 (блок release-127), ITSM-71543
(hub3 too many failed DB queries), ITSM-71546 (bond publish blocked),
ITSM-71593/71594/71640 (redeploy hub4/hub3).

**Заметка дежурному:** пока идёт восстановление, алерты publish blocked/entity
failed на snapshots — ожидаемый побочный эффект, затухают по мере переката
loader. Ставь :eyes:, линкуй к incident-треду и ITSM, новый тикет не создавай.

---

## 2. Snapshot Datacheck / publish blocked — порог 1% failed symbols

Валидация снапшота падает, если доля failed symbols превышает порог **1%** от
успешных (пример: `bond_BCBA: 82 failed symbols > 32.16 (0.01 * 3216)`). Причина
обычно — плохие данные от FactSet ИЛИ каскад из инцидента №1.
Разбор: анализ символов → письмо в FactSet или правка rulesets/ignore в
`symlistfeed-preprocessor` → для *Snapshot Datacheck failed* ручное закрытие в
Zabbix (см. `zabbix-alerts.md`).

---

<!-- Новые повторяющиеся паттерны добавляй сюда: симптом → причина → порядок → тикеты -->
