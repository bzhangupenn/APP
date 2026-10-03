"""Tag AppLovin-pixel sites with a country / region.

Shopify storefronts expose their store country and currency in the page
(`Shopify.country = "SG"`, `Shopify.currency = {"active":"SGD"...}`). For
non-Shopify sites, or when the fetch fails, fall back to the ccTLD.

Usage: python analysis/region.py [--month 2026-09-01]
Reads data/applovin_sites.csv, writes data/site_region.csv.
"""

import argparse
import concurrent.futures as cf
import re
import urllib.request
from pathlib import Path

import pandas as pd

DATA = Path(__file__).resolve().parent / "data"

APAC = {"AU", "NZ", "CN", "HK", "TW", "JP", "KR", "SG", "MY", "TH", "VN", "PH",
        "ID", "IN", "PK", "BD", "LK", "MO", "KH", "MM", "NP"}
TLD_COUNTRY = {"uk": "GB", "com.au": "AU", "co.nz": "NZ", "co.jp": "JP", "co.kr": "KR",
               "com.sg": "SG", "com.my": "MY", "co.th": "TH", "com.vn": "VN",
               "com.ph": "PH", "co.id": "ID", "co.in": "IN", "com.hk": "HK",
               "com.tw": "TW", "com.cn": "CN"}


def tld_country(site):
    host = re.sub(r"^https?://", "", site).split("/")[0].lower()
    for suffix, cc in TLD_COUNTRY.items():
        if host.endswith("." + suffix):
            return cc
    last = host.rsplit(".", 1)[-1]
    return last.upper() if len(last) == 2 else None


def fetch(site):
    try:
        req = urllib.request.Request(site, headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=15).read(400_000).decode("utf-8", "ignore")
    except Exception:
        return site, None, None, False
    country = re.search(r'Shopify\.country\s*=\s*"([A-Z]{2})"', html)
    currency = re.search(r'Shopify\.currency\s*=\s*\{"active":"([A-Z]{3})"', html)
    return (site, country and country.group(1), currency and currency.group(1),
            "s.axon.ai" in html or "axon.ai/pixel" in html)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--month", help="only tag sites seen in this crawl month (default: all)")
    p.add_argument("--workers", type=int, default=32)
    a = p.parse_args()

    df = pd.read_csv(DATA / "applovin_sites.csv")
    if a.month:
        df = df[df.date == a.month]
    sites = sorted(df.site.unique())
    print(f"fetching {len(sites)} sites ...")
    with cf.ThreadPoolExecutor(a.workers) as ex:
        rows = list(ex.map(fetch, sites))
    out = pd.DataFrame(rows, columns=["site", "shopify_country", "shopify_currency", "pixel_live"])
    out["tld_country"] = out.site.map(tld_country)
    out["country"] = out.shopify_country.fillna(out.tld_country)
    out["apac"] = out.country.isin(APAC)
    out.to_csv(DATA / "site_region.csv", index=False)
    print(out.country.value_counts().head(15).to_string())


if __name__ == "__main__":
    main()
