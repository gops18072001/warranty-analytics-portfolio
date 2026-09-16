-- ============================================================================
-- Warranty & Component Quality Analytics - business question set
--
-- Eight questions a quality or supply-chain manager would actually ask.
-- Techniques: multi-table joins, CTEs, window functions (RANK, LAG,
-- running totals, moving averages), conditional aggregation, date grouping.
--
-- Run all:  sqlite3 warranty.db < analysis.sql
-- ============================================================================


-- ---------------------------------------------------------------------------
-- Q1. What is the overall warranty claim rate, and what is it costing us?
--     Headline KPIs for the top of the dashboard.
-- ---------------------------------------------------------------------------
-- NOTE: claims are aggregated to one row per batch BEFORE joining. Joining
-- warranty_claims directly to production_batches fans the batch row out once
-- per claim and multiplies SUM(units_produced) by the claim count - a silent
-- wrong answer, not an error. Same pattern is used in Q2 and Q7.
WITH claims_per_batch AS (
    SELECT batch_id,
           COUNT(*)              AS claims,
           SUM(claim_cost_inr)   AS cost
    FROM warranty_claims
    GROUP BY batch_id
)
SELECT
    COUNT(*)                                     AS batches,
    SUM(pb.units_produced)                       AS units_produced,
    SUM(COALESCE(cpb.claims, 0))                 AS total_claims,
    ROUND(100.0 * SUM(COALESCE(cpb.claims, 0))
          / SUM(pb.units_produced), 3)           AS claim_rate_pct,
    ROUND(SUM(COALESCE(cpb.cost, 0)) / 100000.0, 1) AS total_cost_lakh_inr,
    ROUND(SUM(COALESCE(cpb.cost, 0))
          / NULLIF(SUM(COALESCE(cpb.claims, 0)), 0), 0) AS avg_claim_cost_inr
FROM production_batches pb
LEFT JOIN claims_per_batch cpb ON cpb.batch_id = pb.batch_id;


-- ---------------------------------------------------------------------------
-- Q2. Which suppliers are underperforming?
--     Claim rate per supplier, ranked, with each supplier's share of total
--     warranty cost. RANK() window function over the aggregate.
-- ---------------------------------------------------------------------------
WITH claims_per_batch AS (
    SELECT batch_id, COUNT(*) AS claims, SUM(claim_cost_inr) AS cost
    FROM warranty_claims
    GROUP BY batch_id
),
supplier_stats AS (
    SELECT
        s.supplier_id,
        s.supplier_name,
        s.tier,
        SUM(pb.units_produced)            AS units,
        SUM(COALESCE(cpb.claims, 0))      AS claims,
        SUM(COALESCE(cpb.cost, 0))        AS cost
    FROM suppliers s
    JOIN production_batches pb ON pb.supplier_id = s.supplier_id
    LEFT JOIN claims_per_batch cpb ON cpb.batch_id = pb.batch_id
    GROUP BY s.supplier_id, s.supplier_name, s.tier
)
SELECT
    supplier_name,
    tier,
    units,
    claims,
    ROUND(100.0 * claims / units, 3)                       AS claim_rate_pct,
    RANK() OVER (ORDER BY 1.0 * claims / units DESC)       AS worst_rank,
    ROUND(cost / 100000.0, 1)                              AS cost_lakh_inr,
    ROUND(100.0 * cost / SUM(cost) OVER (), 1)             AS pct_of_total_cost
FROM supplier_stats
ORDER BY claim_rate_pct DESC;


-- ---------------------------------------------------------------------------
-- Q3. Is any supplier getting worse over time?
--     Quarterly claim rate per supplier with LAG() to show the change on the
--     previous quarter. This is the query that surfaces the Shreeji problem.
--
--     READ THE LAST TWO QUARTERS WITH CARE - right-censoring.
--     Parts fail 20-400 days after production, but the data ends 2026-06-30.
--     A batch built in 2026-Q2 has had only weeks to fail, so its claim rate
--     looks near zero and every supplier appears to be improving. That is an
--     artefact of the observation window, not a quality gain. For a like-for-
--     like comparison, restrict to a fixed maturity - e.g. claims within 180
--     days of production, for batches at least 180 days old:
--         WHERE wc.days_to_failure <= 180
--           AND julianday('2026-06-30') - julianday(pb.production_date) >= 180
-- ---------------------------------------------------------------------------
WITH quarterly AS (
    SELECT
        s.supplier_name,
        pb.production_date,
        CAST(strftime('%Y', pb.production_date) AS INTEGER) AS yr,
        (CAST(strftime('%m', pb.production_date) AS INTEGER) + 2) / 3 AS qtr,
        pb.units_produced,
        (SELECT COUNT(*) FROM warranty_claims wc WHERE wc.batch_id = pb.batch_id) AS claims
    FROM production_batches pb
    JOIN suppliers s ON s.supplier_id = pb.supplier_id
),
agg AS (
    SELECT
        supplier_name,
        yr,
        qtr,
        printf('%d-Q%d', yr, qtr)                    AS period,
        SUM(units_produced)                          AS units,
        SUM(claims)                                  AS claims,
        ROUND(100.0 * SUM(claims) / SUM(units_produced), 3) AS claim_rate_pct
    FROM quarterly
    GROUP BY supplier_name, yr, qtr
)
SELECT
    supplier_name,
    period,
    units,
    claims,
    claim_rate_pct,
    LAG(claim_rate_pct) OVER (PARTITION BY supplier_name ORDER BY yr, qtr) AS prev_qtr_pct,
    ROUND(claim_rate_pct
          - LAG(claim_rate_pct) OVER (PARTITION BY supplier_name ORDER BY yr, qtr), 3) AS qoq_change
FROM agg
ORDER BY supplier_name, yr, qtr;


-- ---------------------------------------------------------------------------
-- Q4. Which component and defect pairs drive the most cost?
--     Pareto: cumulative share of warranty spend, so we can say "the top N
--     pairs account for X% of cost". Running total window function.
-- ---------------------------------------------------------------------------
WITH pairs AS (
    SELECT
        c.component_name,
        dt.defect_name,
        dt.severity,
        COUNT(*)                  AS claims,
        SUM(wc.claim_cost_inr)    AS cost
    FROM warranty_claims wc
    JOIN production_batches pb ON pb.batch_id = wc.batch_id
    JOIN components      c  ON c.component_id = pb.component_id
    JOIN defect_types    dt ON dt.defect_id   = wc.defect_id
    GROUP BY c.component_name, dt.defect_name, dt.severity
)
SELECT
    component_name,
    defect_name,
    severity,
    claims,
    ROUND(cost / 100000.0, 1) AS cost_lakh_inr,
    ROUND(100.0 * SUM(cost) OVER (ORDER BY cost DESC
                                  ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
          / SUM(cost) OVER (), 1) AS cumulative_pct_of_cost
FROM pairs
ORDER BY cost DESC
LIMIT 20;


-- ---------------------------------------------------------------------------
-- Q5. How quickly do parts fail after production?
--     Time-to-failure distribution by severity - drives warranty period policy.
-- ---------------------------------------------------------------------------
SELECT
    dt.severity,
    COUNT(*)                                AS claims,
    MIN(wc.days_to_failure)                 AS min_days,
    ROUND(AVG(wc.days_to_failure), 0)       AS avg_days,
    MAX(wc.days_to_failure)                 AS max_days,
    SUM(CASE WHEN wc.days_to_failure <=  90 THEN 1 ELSE 0 END) AS within_90d,
    ROUND(100.0 * SUM(CASE WHEN wc.days_to_failure <= 90 THEN 1 ELSE 0 END)
          / COUNT(*), 1)                    AS pct_within_90d
FROM warranty_claims wc
JOIN defect_types dt ON dt.defect_id = wc.defect_id
GROUP BY dt.severity
ORDER BY claims DESC;


-- ---------------------------------------------------------------------------
-- Q6. Monthly claim trend with a 3-month moving average.
--     Moving average smooths the noise so the trend is readable on a line chart.
-- ---------------------------------------------------------------------------
WITH monthly AS (
    SELECT
        strftime('%Y-%m', wc.failure_date) AS month,
        COUNT(*)                           AS claims,
        SUM(wc.claim_cost_inr)             AS cost
    FROM warranty_claims wc
    GROUP BY strftime('%Y-%m', wc.failure_date)
)
SELECT
    month,
    claims,
    ROUND(cost / 100000.0, 1) AS cost_lakh_inr,
    ROUND(AVG(claims) OVER (ORDER BY month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 0)
        AS claims_3mo_moving_avg
FROM monthly
ORDER BY month;


-- ---------------------------------------------------------------------------
-- Q7. Which plant builds the most reliable product?
--     Normalised by volume so a big plant is not penalised. Includes plant age
--     to test whether older lines actually perform worse.
-- ---------------------------------------------------------------------------
WITH claims_per_batch AS (
    SELECT batch_id, COUNT(*) AS claims, SUM(claim_cost_inr) AS cost
    FROM warranty_claims
    GROUP BY batch_id
)
SELECT
    p.plant_name,
    p.state,
    p.commissioned_year,
    2026 - p.commissioned_year            AS plant_age_years,
    SUM(pb.units_produced)                AS units,
    SUM(COALESCE(cpb.claims, 0))          AS claims,
    ROUND(100.0 * SUM(COALESCE(cpb.claims, 0))
          / SUM(pb.units_produced), 3)    AS claim_rate_pct,
    ROUND(SUM(COALESCE(cpb.cost, 0))
          / SUM(pb.units_produced), 2)    AS warranty_cost_per_unit_inr
FROM plants p
JOIN production_batches pb ON pb.plant_id = p.plant_id
LEFT JOIN claims_per_batch cpb ON cpb.batch_id = pb.batch_id
GROUP BY p.plant_id, p.plant_name, p.state, p.commissioned_year
ORDER BY claim_rate_pct DESC;


-- ---------------------------------------------------------------------------
-- Q8. Flag batches needing investigation.
--     Any batch whose claim rate exceeds 3x its supplier's average - the kind
--     of exception list a quality team works from on Monday morning.
-- ---------------------------------------------------------------------------
WITH batch_rates AS (
    SELECT
        pb.batch_id,
        pb.production_date,
        c.component_name,
        s.supplier_name,
        p.plant_name,
        pb.units_produced,
        COUNT(wc.claim_id) AS claims,
        1.0 * COUNT(wc.claim_id) / pb.units_produced AS rate
    FROM production_batches pb
    JOIN components c ON c.component_id = pb.component_id
    JOIN suppliers  s ON s.supplier_id  = pb.supplier_id
    JOIN plants     p ON p.plant_id     = pb.plant_id
    LEFT JOIN warranty_claims wc ON wc.batch_id = pb.batch_id
    GROUP BY pb.batch_id
    HAVING pb.units_produced >= 1000
)
SELECT
    batch_id,
    production_date,
    component_name,
    supplier_name,
    plant_name,
    units_produced,
    claims,
    ROUND(100.0 * rate, 3) AS batch_claim_rate_pct,
    ROUND(100.0 * AVG(rate) OVER (PARTITION BY supplier_name), 3) AS supplier_avg_pct,
    ROUND(rate / AVG(rate) OVER (PARTITION BY supplier_name), 2)  AS times_supplier_avg
FROM batch_rates
WHERE rate > 3 * (SELECT AVG(rate) FROM batch_rates br WHERE br.supplier_name = batch_rates.supplier_name)
ORDER BY times_supplier_avg DESC
LIMIT 25;
