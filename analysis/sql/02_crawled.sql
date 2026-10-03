-- Every root page crawled each month, so month-over-month "adds" are only
-- counted for sites that were also in the previous month's crawl.
SELECT date, root_page AS site, ANY_VALUE(rank) AS rank
FROM `httparchive.crawl.pages`
WHERE date IN ({dates})
  AND client = 'mobile'
  AND is_root_page
GROUP BY date, site
