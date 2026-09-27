# Contributing

Спасибо за интерес к Felagi Flow. Ниже — как помочь проекту.

## Как сообщить о баге

Создайте issue и укажите:

- **Что происходит** и **что ожидалось**.
- **Шаги воспроизведения** (минимальные).
- Окружение: ОС, способ запуска (Docker / локально), версии Python/Node.
- Логи: `docker compose logs --tail=200` (или вывод консоли).
- Скриншот/текст ошибки, если есть.

Для проблем с выполнением workflow полезно приложить граф (экспорт версии) и
`trigger_payload`, с которым запуск воспроизводится.

## Как предложить изменение (PR)

1. Форкните репозиторий и создайте ветку от `main`.
2. Внесите изменение **небольшими коммитами** (см. «Коммиты» ниже).
3. Убедитесь, что все проверки зелёные (см. «Проверки»).
4. Откройте PR с описанием: что и зачем, как проверяли.
5. Если меняются таблицы БД или контракт API — сначала опишите это в
   обсуждении/issue, затем миграция/код.

Что повышает шансы на приём: тесты на новое поведение, отсутствие регрессий в
существующих, минимальный diff без «попутных» переписываний.

## Проверки

Перед PR — все должны быть зелёными.

**Backend:**

```bash
cd backend
ruff check .
mypy .
# с Postgres, иначе @pytest.mark.postgres пропускаются:
TEST_DATABASE_URL="postgresql+asyncpg://felagi:change_me_in_prod@127.0.0.1:5432/felagi_test" pytest
```

**Frontend:**

```bash
cd frontend
npx tsc --noEmit
npx vitest run
```

То же самое гоняет CI (`.github/workflows/ci.yml`): backend, frontend (typecheck
+ тесты + build), compose-smoke, E2E.

## Code style

- **Backend:** ruff (правила `E,F,I,UP,B,SIM,RUF`) и mypy в режиме `strict`.
  `# type: ignore` не используется — для библиотек без типов правьте
  `[[tool.mypy.overrides]]` в `pyproject.toml`.
- **Frontend:** TypeScript strict. `@ts-ignore` не используется; для этого же —
  корректные типы.
- **Общее:** не отключайте проверки и не правьте тесты, чтобы они «проходили».
  Если тест неверен — объясните это в PR.

## Коммиты

[Conventional Commits](https://www.conventionalcommits.org/), сообщение на
английском:

```
feat(engine): add Telegram action node
fix(ui): refresh execution metadata from rest after finish
docs: describe queue internals
chore(ci): add playwright job
```

Тип (`feat`/`fix`/`docs`/`chore`/`refactor`/`test`) + необязательный scope +
краткое описание в императиве. В теле — «почему», если неочевидно.

Не добавляйте в коммиты строки вида `Co-Authored-By` — автором должен быть
человек.

## Добавление типа узла

Пошаговая инструкция (5 шагов) — в
[`docs/development.md`](docs/development.md#как-добавить-новый-тип-узла-5-шагов).