SELECT
    LOWER(CAST(taker AS VARCHAR)) AS address,
    COUNT(*) AS trades_30d,
    COUNT(DISTINCT token_bought_address) AS token_diversity,
    COUNT(DISTINCT block_number) AS unique_blocks
FROM dex.trades
WHERE block_date >= CURRENT_DATE - INTERVAL '30' DAY
    AND blockchain = 'ethereum'
GROUP BY taker
HAVING COUNT(*) >= 3000
    AND COUNT(*) * 1.0 / COUNT(DISTINCT block_number) >= 0.8
ORDER BY trades_30d DESC
LIMIT 50;
