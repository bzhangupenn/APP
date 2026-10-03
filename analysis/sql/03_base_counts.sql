-- Monthly install base per pixel (exhibit-1 comparison vs Snap / Pinterest).
SELECT
  m.date,
  c.crawled_sites,
  COUNTIF(applovin) AS applovin,
  COUNTIF(applovin_domain) AS applovin_domain,
  COUNTIF(snap) AS snap,
  COUNTIF(pinterest) AS pinterest,
  COUNTIF(tiktok) AS tiktok,
  COUNTIF(applovin AND shopify) AS applovin_shopify
FROM `{project}.{dataset}.site_month` m
JOIN (SELECT date, COUNT(*) AS crawled_sites FROM `{project}.{dataset}.crawled` GROUP BY date) c
  USING (date)
GROUP BY m.date, c.crawled_sites
ORDER BY m.date
