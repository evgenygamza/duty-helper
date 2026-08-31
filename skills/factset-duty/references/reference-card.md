# Справочник дежурного FactSet

Быстрый доступ к ссылкам, каналам и доступам. Онбординг в дежурство:
попросить @Ivan Grigorev показать логи и Zabbix (prod + тестовые), запросить
недостающие доступы через ACC-тикет.

## Дашборды и трекеры

- **Переписка с FactSet** — Jira board **FFD-318**
- **Скрам-доска команды** — Jira board **FFD-323**
- **Freshdesk** (репорты саппорта, тег `factset QA`) — очередь FactSet QA
- **logviewer** — `dashboard.xtools.tv/dashboard-prod/#/logviewer2`
- **Branches Map** — `branches-map.xtools.tv`
- Zabbix — состояние сервисов; Grafana — метрики k8s; ArgoCD — деплой

- **Задача дежурства** — `Duty on Sprint <спринт>` в FFD, тип `Assignment`;
  assignee = текущий дежурный (см. `duty-channel.md`)
- **График дежурств** — гугл-таблица, ссылка в описании задачи дежурства
- **Процесс дежурства** — `kb.xtools.tv` стр. `154640786`

## Каналы Slack (роль в дежурстве)

**Канал дежурства (наш, приватный):**
- #factset-duty `C0BRG8GJNGN` — карточки обращений и дайджест

**Ветка данных (мониторить):**
- #team-factset `CDTG7MX1S` — открытые обращения
- #team-factset-internal `C06T9BAEWMQ` — внутренняя, эскалация `@factset-dev`
- #support-data-issues `C455B0B25` — проблемы данных на проде
- проектные: #proj-screener `C46FZNPSA`, #proj-datafeeds `C46FX9XJB`,
  #proj-pine `C03AZCCPWR4`, #proj-ipo, #proj-bonds
- #cluster-data-integration(-qa) — коммуникация кластера

**Ветка алертов (мониторить):**
- #factset-disasters-prod `C05MSPMHZU1`, #factset-disasters-stable
- #factset-loaders-disasters-staging (loader критичен для стендов)
- #factset-ipo-alerts, #factset-data-checker-prod/staging `C072Z0Q8NDU`

**Не мониторить постоянно:** #factset-mr, #factset-tasks, #factset-disasters (архив)

## Группы (subteam)

- `@qa-factset-dutyman` = `S03JHT8QBV5` — призывы по данным (люди)
- `@qa_factset` — алерты (Zabbix)
- `@factset-dev` — разработчики команды (эскалация)

## Регламент (Confluence, space FFD)

- Дежурство по данным — `270632861`
- Мониторинг Zabbix триггеров — `691109982`
- Дежурство (обзор) — `853442647`
- Общие советы по разбору проблем (XWIKI) — `404164432`
- Онбординг — «QA Onboarding» в space FFD

## Стенды (qa-automation)

`hub0`, `hub01`, `dal2`, `hub3`, `snapshot`. Прод-хабы: hub3 / hub4.
