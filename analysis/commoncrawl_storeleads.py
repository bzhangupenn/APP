"""Recover archived Store Leads AppLovin pages from Common Crawl.

Store Leads only shows the current report. Common Crawl's monthly crawls
sample storeleads.app; this scans each crawl's columnar URL index for
AppLovin pages, downloads the archived HTML, and saves the store counts
as of each page's "Updated" date to data/storeleads/commoncrawl_country_pages.json.

Usage: python analysis/commoncrawl_storeleads.py CC-MAIN-2026-30 CC-MAIN-2026-34 ...
(needs: pip install duckdb pytz)
"""

import gzip
import json
import re
import sys
import urllib.request
from pathlib import Path

import duckdb

OUT = Path(__file__).resolve().parent / "data" / "storeleads" / "commoncrawl_country_pages.json"
CC = "https://data.commoncrawl.org/"


def index_hits(con, crawl):
    paths = gzip.decompress(urllib.request.urlopen(f"{CC}crawl-data/{crawl}/cc-index-table.paths.gz").read())
    files = [CC + p for p in paths.decode().split() if "subset=warc" in p]
    # The index is sorted by SURT key, so this range only reads storeleads.app row groups.
    rows = con.execute(f"""
        SELECT url, warc_filename, warc_record_offset, warc_record_length
        FROM read_parquet({files!r})
        WHERE url_surtkey >= 'app,storeleads)' AND url_surtkey < 'app,storeleads*'
          AND fetch_status = 200""").fetchall()
    return [r for r in rows if "applovin" in r[0].lower()]


def fetch_record(warc, offset, length):
    req = urllib.request.Request(CC + warc, headers={"Range": f"bytes={offset}-{offset + length - 1}"})
    raw = gzip.decompress(urllib.request.urlopen(req, timeout=60).read()).decode("utf-8", "ignore")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>", " ", raw, flags=re.S)))


def main():
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    found = json.loads(OUT.read_text()) if OUT.exists() else []
    seen = {(r["url"], r["updated"]) for r in found}
    for crawl in sys.argv[1:]:
        hits = index_hits(con, crawl)
        print(f"{crawl}: {len(hits)} AppLovin pages")
        for url, warc, off, length in hits:
            text = fetch_record(warc, off, length)
            updated = re.search(r"Updated (\w+ \d+ \d{4})", text)
            n = re.search(r"installed on ([\d,]+) ecommerce stores in", text)
            if not (updated and n) or (url, updated.group(1)) in seen:
                continue
            found.append({"url": url, "crawl": crawl, "updated": updated.group(1),
                          "country": url.rsplit("/", 1)[-1], "stores": int(n.group(1).replace(",", ""))})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(sorted(found, key=lambda r: (r["updated"], r["country"])), indent=1))
    print(f"wrote {OUT} ({len(found)} records)")


if __name__ == "__main__":
    main()
