Modify the planner system prompt for the Data-Agent-MCP project to improve how it plans SQL and Python execution.

## Primary Goal

Make the planner generate **answer-oriented execution plans** rather than plans that retrieve unnecessarily large intermediate datasets.

The planner must optimize for:

> Retrieve and compute the minimum amount of data necessary to answer the user's question correctly.

The planner should understand that SQL and Python are not merely interchangeable execution tools. SQL should be used as the primary relational/data-reduction layer, while Python should be used for computations, statistics, visualization, and operations that are better suited to Python.

---

## 1. Make SQL answer-oriented

When a task can be expressed using SQL, the planner should prefer SQL operations that reduce the dataset before passing results to downstream steps.

SQL should be preferred for:

- filtering rows with `WHERE`
- selecting only required columns
- aggregation with `SUM`, `AVG`, `COUNT`, `MIN`, `MAX`, etc.
- `GROUP BY`
- sorting with `ORDER BY`
- ranking
- `LIMIT`
- deduplication
- joins
- date/time grouping
- window functions
- other relational transformations
- reducing large datasets before Python execution

The planner should explicitly avoid plans that retrieve raw or unnecessarily large datasets when a smaller SQL result can answer the question.

For example, for:

"Show me the top 5 products by revenue."

Prefer a plan equivalent to:

1. Use SQL to aggregate revenue by product.
2. Sort by revenue descending.
3. Limit the result to 5 rows.
4. Return the small result.

Do NOT plan:

1. Retrieve all sales records.
2. Pass all sales records to Python.
3. Calculate product revenue.
4. Sort and select the top 5.

---

## 2. SQL should minimize downstream data

When SQL output will be consumed by Python, the planner should deliberately minimize the SQL result before passing it to Python.

For example, for:

"Plot monthly revenue for the top 5 products in 2025."

Prefer:

1. SQL filters the data to 2025.
2. SQL determines the top 5 products.
3. SQL aggregates revenue by product and month.
4. SQL returns only the resulting rows required for the chart.
5. Python creates the visualization from this compact result.

Do NOT retrieve the entire 2025 dataset and ask Python to perform all filtering, grouping, and aggregation unless SQL genuinely cannot perform the required operation.

The planner should treat SQL as a **data reduction layer**.

---

## 3. Do not confuse multi-step reasoning with multiple execution operations

A plan may contain multiple conceptual reasoning steps without requiring multiple SQL or Python executions.

The planner must distinguish between:

### A. Logical reasoning steps

These describe what needs to be determined.

Example:

1. Determine which products have the highest revenue.
2. Determine their monthly revenue.
3. Visualize the result.

### B. Execution boundaries

These describe when an actual tool/code execution is necessary.

The planner should combine multiple SQL operations into a single SQL query when they can be expressed efficiently together using:

- CTEs
- subqueries
- joins
- aggregations
- window functions
- filtering
- ordering
- other SQL constructs

Similarly, combine multiple related Python operations into a single Python execution when they can be performed together safely.

Do NOT create multiple execution steps merely because the reasoning contains multiple sub-steps.

For example:

BAD:

1. SQL: filter 2025.
2. SQL: calculate top products.
3. SQL: calculate monthly revenue.
4. Python: create chart.

BETTER:

1. SQL: filter, determine top products, aggregate monthly revenue, and return the compact result.
2. Python: create the chart.

The planner should optimize for **logical clarity without unnecessary execution boundaries**.

---

## 4. Choose SQL vs Python based on the operation

Use SQL when the task is primarily relational or can efficiently reduce the dataset.

Use Python when the task requires:

- complex numerical computation
- statistical analysis
- machine learning
- custom algorithms
- scientific computing
- visualization
- matplotlib
- NumPy/SciPy-specific functionality
- operations that are awkward or impractical in SQL

For mixed tasks:

> Prefer SQL first to filter, join, aggregate, and reduce the data, then use Python for the remaining analytical or visualization work.

Example:

User:
"Calculate the average monthly revenue, determine its standard deviation, and plot the monthly trend."

Possible plan:

1. SQL: aggregate raw sales into monthly revenue.
2. Python: calculate statistical metrics and generate the chart.

Do not send all raw sales records to Python if SQL can reduce them to monthly values first.

---

## 5. Avoid unnecessarily large SQL results

The planner should actively consider result cardinality.

Before generating a SQL execution step, ask internally:

- Do I need every row?
- Can aggregation reduce the result?
- Can filtering reduce the result?
- Can I select fewer columns?
- Can `LIMIT` be safely used?
- Can ranking/top-N eliminate irrelevant rows?
- Will this result be passed to Python?
- Can SQL produce exactly the dataset required by the next operation?

The planner should avoid `SELECT *` unless the user genuinely needs the complete records or downstream processing genuinely requires all columns.

Prefer:

```sql
SELECT product, SUM(revenue) AS total_revenue
...
```

over:

```sql
SELECT *
...
```

when only aggregated revenue is required.

---

## 6. Do not use LIMIT as a substitute for correct analysis

The planner must NOT arbitrarily add `LIMIT` simply to make results smaller.

For example, this is WRONG:

```sql
SELECT *
FROM sales
LIMIT 100;
```

if the user asks:

"Which product generated the most revenue?"

The first 100 rows cannot reliably answer that question.

Instead, perform the complete relevant computation:

```sql
SELECT
    product,
    SUM(revenue) AS total_revenue
FROM sales
GROUP BY product
ORDER BY total_revenue DESC
LIMIT 1;
```

The principle is:

> Reduce the result through correct computation, not arbitrary truncation.

---

## 7. Design SQL outputs for downstream consumers

The planner should consider what the next node needs.

If Python needs data for a chart, SQL should return chart-ready data.

If the final answer only needs a few metrics, SQL should return those metrics.

If another analytical operation requires detailed rows, return those rows only when they are genuinely necessary.

Examples:

### User asks for a single metric

Return:

```text
COUNT / SUM / AVG / MIN / MAX
```

rather than all underlying records.

### User asks for top N

Return:

```text
ORDER BY ... DESC
LIMIT N
```

rather than all groups.

### User asks for a trend

Return:

```text
time_period + aggregated_metric
```

rather than raw transactions.

### User asks for a visualization

Return only the dimensions and measures required for that visualization.

---

## 8. Preserve correctness

Optimization must never change the meaning of the requested analysis.

The planner must ensure that SQL reduction happens only after determining what information is actually required.

Do not:

- arbitrarily sample data
- arbitrarily truncate rows
- discard columns needed for downstream analysis
- approximate a result without being asked
- move computation to Python solely to avoid writing SQL
- use a small sample to answer a question requiring complete data

The goal is:

> smallest sufficient dataset, not smallest possible dataset.

---

## 9. Plan for the final formatting node

The final formatting LLM should not need to inspect thousands of raw rows.

Therefore, whenever possible, the planner should produce execution results that are already **answer-oriented**.

For example:

Instead of:

```text
SQL → 1000 transaction rows → Final LLM
```

prefer:

```text
SQL → relevant aggregates/top-N/statistics → Final LLM
```

For visualization:

```text
SQL → compact chart-ready dataset → Python → artifact
```

The final answer should be based on meaningful computed results rather than raw execution dumps.

---

## 10. Add explicit planning principles

Add a concise set of planner rules similar to the following:

### Data Reduction Principle

Always minimize intermediate datasets while preserving all information required for the requested analysis.

### SQL Pushdown Principle

Perform filtering, projection, joining, grouping, aggregation, sorting, ranking, and other relational operations in SQL whenever practical.

### Execution Consolidation Principle

Combine related operations into one execution when they can be safely expressed together. Multiple reasoning steps do not automatically imply multiple tool executions.

### Python Specialization Principle

Use Python for computation, statistics, visualization, machine learning, and specialized numerical operations that are better suited to Python.

### Downstream Awareness Principle

When one execution feeds another, generate the upstream result specifically for the downstream operation rather than returning unnecessary raw data.

### Correctness-over-Compression Principle

Never reduce data through arbitrary sampling or truncation when doing so could change the answer.

---

## 11. Preserve the existing planner behavior

Do not rewrite unrelated planner logic.

Do not change:

- existing state fields
- tool names
- execution node interfaces
- SQL/Python execution implementation
- graph topology
- error handling
- retry behavior
- MCP integration

unless required to implement the planner-prompt improvements.

The primary requested change is to the **planner system prompt and its planning behavior**.

First inspect the existing planner system prompt and understand its current rules. Then modify it rather than replacing useful existing instructions.

Ensure the resulting prompt remains internally consistent and does not contain contradictory instructions.

---

## 12. Add examples to the planner prompt

Include a few concise examples demonstrating the intended behavior.

### Example 1 — Aggregation

User:

"What is the average revenue by country?"

Preferred:

```text
SQL:
GROUP BY country
AVG(revenue)
```

Not:

```text
SQL:
retrieve all rows
Python:
group and calculate average
```

### Example 2 — Top N

User:

"What are the top 10 products by revenue?"

Preferred:

```text
SQL:
GROUP BY product
SUM(revenue)
ORDER BY revenue DESC
LIMIT 10
```

### Example 3 — SQL + Python

User:

"Plot monthly sales for the top 5 products."

Preferred:

```text
SQL:
identify top 5 products and aggregate monthly sales

Python:
generate visualization from the compact SQL result
```

### Example 4 — Python-specific computation

User:

"Calculate Pearson correlation between age and income and plot the relationship."

Preferred:

```text
Python:
calculate correlation and create visualization
```

Do not unnecessarily introduce SQL if SQL provides no meaningful advantage.

---

## Final requirement

After modifying the planner prompt, review it against these questions:

1. Does the planner prefer SQL for relational data reduction?
2. Does it avoid unnecessary `SELECT *`?
3. Does it produce compact, answer-oriented SQL results?
4. Does it distinguish reasoning steps from execution boundaries?
5. Does it combine multiple SQL operations when one query can perform them?
6. Does it combine related Python operations when appropriate?
7. Does it use SQL before Python for mixed analytical tasks when SQL can reduce the data?
8. Does it avoid arbitrary `LIMIT`/sampling that could produce incorrect answers?
9. Does it avoid unnecessarily passing large datasets to downstream nodes or the final LLM?
10. Does it preserve all existing planner capabilities and project-specific constraints?

Make the changes directly in the relevant planner prompt file/code and show the final modified prompt and a concise summary of what changed.
