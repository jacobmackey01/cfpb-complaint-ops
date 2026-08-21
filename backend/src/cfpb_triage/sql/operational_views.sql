CREATE OR REPLACE VIEW operational_cases AS
SELECT
    c.*,
    CASE
        WHEN c.prediction_abstained THEN TRUE
        WHEN c.timely IS FALSE THEN TRUE
        WHEN c.has_narrative IS FALSE THEN TRUE
        ELSE FALSE
    END AS requires_manual_attention,
    list_filter([
        CASE WHEN c.prediction_abstained THEN 'uncertain_model_route' END,
        CASE WHEN c.timely IS FALSE THEN 'untimely_company_response' END,
        CASE WHEN c.has_narrative IS FALSE THEN 'no_published_narrative' END
    ], item -> item IS NOT NULL) AS attention_reasons
FROM complaints c;

CREATE OR REPLACE VIEW daily_product_volume AS
SELECT date_received AS date, product AS label, count(*)::BIGINT AS count
FROM complaints
GROUP BY 1, 2;

CREATE OR REPLACE VIEW daily_issue_volume AS
SELECT date_received AS date, issue AS label, count(*)::BIGINT AS count
FROM complaints
GROUP BY 1, 2;

CREATE OR REPLACE VIEW monthly_response_metrics AS
SELECT
    date_trunc('month', date_received)::DATE AS month,
    product,
    count(*)::BIGINT AS complaint_count,
    count(*) FILTER (WHERE timely IS NOT NULL)::BIGINT AS response_status_denominator,
    count(*) FILTER (WHERE timely IS TRUE)::BIGINT AS timely_response_count,
    CASE
        WHEN count(*) FILTER (WHERE timely IS NOT NULL) = 0 THEN NULL
        ELSE count(*) FILTER (WHERE timely IS TRUE)::DOUBLE
             / count(*) FILTER (WHERE timely IS NOT NULL)
    END AS timely_response_rate
FROM complaints
GROUP BY 1, 2;
