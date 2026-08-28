# Independent regression suite (production-like Oracle requests)

`scripts/regression_suite.py` is a small, independently authored regression
suite. Its 10 prompts are written fresh for this suite — they are NOT taken
from, derived from, or paraphrases of the held-out execution catalog
(`llm_task_catalog_eval.jsonl`). Expected values come from the known seed data
in `reset_lab_schemas.py`.

## Design

For each case (schema + business-style prompt):
1. Reset the target lab schema to pristine.
2. Ask the deployed adapter (OpenAI-compatible endpoint) for SQL-only.
3. Execute the model's returned SQL against live Oracle as the schema user.
4. Run a KNOWN validation query (correct table/column names) to confirm the
   expected seed value is present — separating "model SQL failed" from
   "the data isn't there."

## Result on sql_only-qlora v1.0.0 (2026-08-28)

**0/10 model SQL executed.** Every case returned `ORA-00942: table or view not
found`. The independently-authored validation queries all found the expected
seed values (`found=True`), confirming the schemas/data are correct and the
failure is entirely the model's object-name generation.

Example model output for a SALES_LAB prompt:

    SELECT c.cust_name, SUM(o.order_total) AS total_spent
    FROM customers c
    JOIN orders o ON o.customer_id = c.customer_id
    GROUP BY c.cust_name ORDER BY total_spent DESC;

The model invents generic tables (`customers`, `orders`) instead of the real
`llm_sales_orders` / `llm_sales_regions` objects, even when the schema name is
given in the prompt. This is the same dominant failure (81/126 = ORA-00942)
identified in `docs/reports/failure-taxonomy-sql-only-v1.md`.

## Usage

```bash
# Requires: live Oracle (env creds) + a deployed adapter on the endpoint.
python scripts/regression_suite.py --base-url http://127.0.0.1:8800
```

## Conclusion

The regression suite is a working, independent gate. It currently fails 10/10,
which is an honest reflection that the released sql_only adapter does not yet
generate schema-correct object names — this is the target for the next
challenger experiment (Step 5), which will add verified schema-grounded
training examples and re-run this suite as a complementary (non-held-out)
check.
