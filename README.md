# mito-harness

Harness, превращающий LLM в аккуратного научного аналитика по **митохондриальной
медицине**: ищет свежую литературу и регистрации исследований, извлекает
структурированные данные, сравнивает митохондриально-таргетные препараты со
стандартом лечения, оценивает перспективность направлений и строит честные
визуализации.

> Исследовательский инструмент. **Не** медицинский советник. Мини-обзор, а не
> систематический обзор/мета-анализ (ограничения явно указаны в каждом отчёте).

## Архитектура

```
main.py ──> RootOrchestrator (метапромпт: план -> делегирование -> агрегация)
             │  план валидируется по реестру шагов; бюджеты:
             │  <=12 шагов, wall-clock 90 мин, UsageLimits на вызов
             │
             ├─ LiteratureSearchAgent  [tools: pubmed_search, europepmc_search, ctgov_search]
             ├─ DataExtractorAgent     [tool: parse_record]            [skill: extraction_rules]
             ├─ ComparativeAnalyst     [tool: compute_plot]            [skill: evidence_levels]
             ├─ ProspectsEvaluator                                     [skills: prospects_criteria, evidence_levels]
             ├─ VisualizerAgent        [tool: compute_plot]
             ├─ ReporterAgent                                          (русскоязычный нарратив)
             └─ ReviewerValidator      [tool: verify_citation]         [skill: citation_checklist]
                    └─ feedback-луп: до 3 итераций правок -> деэскалация
                       (непроверяемые утверждения удаляются в «Отклонено ревьюером»)
```

- **Скиллы** лежат в `skills/<name>/SKILL.md` (формат Anthropic Agent Skills) и
  подгружаются в runtime в системный промпт нужного субагента; каждая инъекция
  логируется событием `skill_loaded`.
- **Анти-галлюцинационный контракт**: экстракция только из реально fetched
  аннотаций; каждое утверждение несёт PMID/NCT/DOI, перепроверенный через
  `verify_citation`; строгие Pydantic-схемы на всех выходах агентов.
- **Честные графики**: один маркер = одно исследование, кодирование только
  направления эффекта, цвет = уровень доказательности, аннотации PMID/NCT,
  футер-дисклеймер. Без усреднения эффекта между исследованиями.

## Отчёты

Готовые результаты живых прогонов — в [`reports/`](reports/INDEX.md):
два мини-обзора на русском (broad и narrow запросы) с верифицированными
ссылками и по 3 графика каждый.

## Быстрый старт

### uv (разработка)

```bash
uv sync
uv run main.py               # оба демо-запроса
uv run main.py --query narrow --refresh
uv run pytest test/          # оффлайн-набор тестов
```

### Docker

```bash
docker compose build
docker compose run harness            # доступ к локальному vLLM через network_mode: host
docker compose run harness python main.py --query broad
```

## Конфигурация

- `harness.yaml` — эндпоинт модели, бюджеты (шаги/токены/wall-clock), пути.
- `config/queries.yaml` — демо-запросы, заболевания, препараты, стандарты лечения.
- `config/sources.yaml` — эндпоинты API, таймауты, ретраи, rate-limit.
- `.env` (копия из `.env.example`) — `OPENAI_BASE_URL` (по умолчанию локальный
  vLLM `http://localhost:8000/v1`), `OPENAI_API_KEY`, `MITO_MODEL`,
  опционально `NCBI_API_KEY` (поднимает лимит PubMed с 3 до 10 req/s).
  Свап на любого облачного провайдера — без правки кода.
- Ответы API кэшируются в `data/cache` для воспроизводимых повторов
  (`--refresh` сбрасывает кэш).

## Пример лога (цепочка делегирований)

```
21:27:18 [plan_created] - - goal=Compare mitochondria-targeted drugs ... steps=['search-mito-lhon:search', ...]
21:27:18 [task_delegated] literature_search -
21:27:44 [tool_result] literature_search - terms=(elamipretide OR SS-31) AND ... hits=8
21:28:02 [skill_loaded] - - skill=extraction_rules chars=1913
21:30:10 [review_feedback] reviewer_validator - iteration=1 approved=true findings=0
21:31:02 [run_finished] - - status=ok records=12 plots=3
```

Полный JSONL-след каждого прогона: `outputs/run_<id>.jsonl` (события:
`run_started`, `plan_created`, `task_delegated/completed/failed`,
`tool_called/result`, `skill_loaded`, `review_feedback`, `iteration_exhausted`,
`budget_degraded`, `run_finished`; поля: `ts, event, run_id, step_id, agent,
tool, correlation_id, duration_ms, payload`).

## Результаты

На каждый прогон — каталог `outputs/run_<id>/`:
- `report_<query>.md` — русский мини-обзор (8 разделов, включая верифицированные
  ссылки и приложение «Отклонено ревьюером»);
- `effect_direction.png`, `prospects_ranking.png`, `gap_map.png`.

## Известные ограничения и как они закрываются

| Ограничение | Митигация |
|---|---|
| LLM может галлюцинировать числа/ссылки | строгие схемы, экстракция только из fetched текста, ревьюер пере-fetch'ает каждый идентификатор |
| Разнородные исходы несопоставимы | синтез только по направлению эффекта (effect-direction plot), без мета-анализа |
| Разреженные данные по части препаратов | один логируемый replan с расширением синонимов, далее честная пометка `preclinical` |
| Качество локальной модели 27B | few-shot промпты + ретраи валидации; свап `MITO_MODEL` на более сильный эндпоинт |
| Риск зависания по времени/токенам | тройной бюджет: лимит шагов плана, UsageLimits, wall-clock с graceful degradation |

## Воспроизведение демо

```bash
uv sync && uv run main.py
```

Тайминги на single-GPU vLLM (Qwen3.8-27B-FP8, concurrency 8): первый live-прогон
~50–80 минут на запрос (экстракция + анализ + review-луп до 3 итераций);
повторный прогон тех же запросов replay'ится из комбинированного HTTP+LLM кэша
за минуты; `--refresh` — полностью live-режим. С облачным эндпоинтом (`.env`)
время пропорционально сокращается.
