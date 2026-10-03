-- One row per (crawl month, site) for every site in the HTTP Archive mobile
-- root-page crawl that loads at least one tracked ad pixel.
-- Materialized into {project}.{dataset}.site_month so later steps are cheap.
SELECT
  date,
  root_page AS site,
  ANY_VALUE(rank) AS rank,
  LOGICAL_OR(NET.HOST(url) = 's.axon.ai') AS applovin,
  LOGICAL_OR(NET.HOST(url) LIKE '%applovin.com') AS applovin_domain,
  LOGICAL_OR(NET.HOST(url) = 'sc-static.net' AND url LIKE '%scevent%') AS snap,
  LOGICAL_OR(NET.HOST(url) = 's.pinimg.com' AND url LIKE '%/ct/%') AS pinterest,
  LOGICAL_OR(NET.HOST(url) = 'analytics.tiktok.com') AS tiktok,
  LOGICAL_OR(NET.HOST(url) = 'cdn.shopify.com' OR NET.HOST(url) LIKE '%.myshopify.com') AS shopify
FROM `httparchive.crawl.requests`
WHERE date IN ({dates})
  AND client = 'mobile'
  AND is_root_page
  AND (NET.HOST(url) IN ('s.axon.ai', 'sc-static.net', 's.pinimg.com', 'analytics.tiktok.com', 'cdn.shopify.com')
       OR NET.HOST(url) LIKE '%applovin.com'
       OR NET.HOST(url) LIKE '%.myshopify.com')
GROUP BY date, site
HAVING applovin OR applovin_domain OR snap OR pinterest OR tiktok
