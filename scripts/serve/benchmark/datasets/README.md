# Benchmark Datasets

## Source
[BIRD-SQL Mini-Dev](https://github.com/bird-bench/mini_dev) — 500 questions from the BIRD benchmark dev set.

License: CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/)

## Files
- `bird-mini-dev.json` — 500 questions across 11 databases (the official BIRD mini-dev subset)

## Schema
```json
{
  "question_id": 1500,
  "db_id": "debit_card_specializing",
  "question": "Please list the product description...",
  "evidence": "hint text for the question",
  "SQL": "SELECT ... (gold SQL, PostgreSQL dialect)",
  "difficulty": "simple|moderate|challenging"
}
```

## Categories (derived at runtime)
The benchmark runner classifies questions by gold SQL patterns:
- `aggregation` — contains COUNT/SUM/AVG/MAX/MIN/GROUP BY/HAVING/CASE WHEN
- `non-aggregation` — simple SELECT without aggregation
