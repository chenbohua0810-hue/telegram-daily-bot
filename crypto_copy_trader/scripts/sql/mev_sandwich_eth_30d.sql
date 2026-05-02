SELECT
    LOWER(CAST(searcher_eoa AS VARCHAR)) AS address,
    SUM(profit_usd) AS profit_30d,
    COUNT(*) AS sandwich_count
FROM mev.sandwich_aggregated_summary
WHERE block_date >= CURRENT_DATE - INTERVAL '30' DAY
    AND blockchain = 'ethereum'
    AND profit_usd > 0
GROUP BY searcher_eoa
HAVING SUM(profit_usd) >= 5000 AND COUNT(*) >= 20
ORDER BY profit_30d DESC
LIMIT 100;
