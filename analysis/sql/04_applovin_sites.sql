-- Site-level AppLovin panel: one row per (month, site) loading the Axon pixel,
-- plus whether the site was crawled / had the pixel in the previous crawl month.
WITH months AS (
  SELECT date, LAG(date) OVER (ORDER BY date) AS prev_date
  FROM (SELECT DISTINCT date FROM `{project}.{dataset}.crawled`)
),
al AS (
  SELECT date, site, rank, shopify
  FROM `{project}.{dataset}.site_month`
  WHERE applovin
)
SELECT
  al.date,
  al.site,
  al.rank,
  al.shopify,
  months.prev_date,
  prev_crawl.site IS NOT NULL AS crawled_prev,
  prev_al.site IS NOT NULL AS applovin_prev
FROM al
JOIN months USING (date)
LEFT JOIN `{project}.{dataset}.crawled` prev_crawl
  ON prev_crawl.date = months.prev_date AND prev_crawl.site = al.site
LEFT JOIN al prev_al
  ON prev_al.date = months.prev_date AND prev_al.site = al.site
ORDER BY al.date, al.site
