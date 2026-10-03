"""Track the country mix of stores running the AppLovin AXON Pixel over time.

Source: Store Leads' free technology report
(storeleads.app/reports/technology/AppLovin AXON Pixel), which covers every
ecommerce platform, not just the Shopify app. The main page carries the full
weekly install history since Jan 2025; each country page carries only that
country's current count. History for country counts therefore comes from
(a) our own dated snapshots in data/storeleads/pixel/ (run this weekly), and
(b) the copies Common Crawl archived (see commoncrawl_storeleads.py).

Usage: python analysis/storeleads_pixel.py [--offline]
"""

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd
import pycountry

ROOT = Path(__file__).resolve().parent
SNAP = ROOT / "data" / "storeleads" / "pixel"
CC_FILE = ROOT / "data" / "storeleads" / "commoncrawl_country_pages.json"
OUT = ROOT / "output"
REPORT = "https://storeleads.app/reports/technology/" + urllib.parse.quote("AppLovin AXON Pixel")
APAC = {"AU", "NZ", "CN", "HK", "TW", "JP", "KR", "SG", "MY", "TH", "VN", "PH",
        "ID", "IN", "PK", "BD", "LK", "MO", "KH", "MM", "NP"}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")


def js_var(page, name):
    m = re.search(rf"var {name} = (\[.*?\]);", page)
    return json.loads(m.group(1)) if m else []


def country_count(cc):
    try:
        page = get(f"{REPORT}/country/{cc}")
    except urllib.error.HTTPError as e:
        return cc, 0 if e.code == 404 else None  # 404 = no stores in that country
    m = re.search(r"installed on ([\d,]+) ecommerce stores in", page)
    return cc, int(m.group(1).replace(",", "")) if m else None


def snapshot():
    page = get(REPORT)
    with cf.ThreadPoolExecutor(8) as ex:
        countries = dict(ex.map(country_count, [c.alpha_2 for c in pycountry.countries]))
    top = {c["term"]: c["count"] for c in js_var(page, "countryData")}
    data = {
        "fetched": dt.date.today().isoformat(),
        "updated": re.search(r"Updated (\w+ \d+ \d{4})", page).group(1),
        "installs": int(re.search(r"currently installed on ([\d,]+)", page).group(1).replace(",", "")),
        "weekly_installs": js_var(page, "installData"),
        "platforms": {p["label"]: p["count"] for p in js_var(page, "providerData")},
        "countries": {k: v for k, v in countries.items() if v},
        "unknown_country": top.get("Unknown", 0),
        "failed_countries": [k for k, v in countries.items() if v is None],
    }
    SNAP.mkdir(parents=True, exist_ok=True)
    path = SNAP / f"{data['fetched']}.json"
    path.write_text(json.dumps(data, indent=1))
    print(f"saved {path}; country sum {sum(data['countries'].values()) + data['unknown_country']:,}"
          f" vs total {data['installs']:,}; failed: {data['failed_countries'] or 'none'}")
    return data


def as_of(updated):
    return dt.datetime.strptime(updated, "%b %d %Y").date()


def history(snaps):
    """Long table: report date, country, stores, source."""
    rows = []
    for s in snaps:
        d = as_of(s["updated"])
        rows += [(d, cc, n, "snapshot") for cc, n in s["countries"].items()]
        rows.append((d, "Unknown", s["unknown_country"], "snapshot"))
    if CC_FILE.exists():
        rows += [(as_of(r["updated"]), r["country"], r["stores"], "commoncrawl")
                 for r in json.loads(CC_FILE.read_text())]
    df = pd.DataFrame(rows, columns=["as_of", "country", "stores", "source"]).drop_duplicates(["as_of", "country"])
    return df.sort_values(["as_of", "country"])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--offline", action="store_true")
    a = p.parse_args()
    if not a.offline:
        snapshot()
    snaps = [json.loads(f.read_text()) for f in sorted(SNAP.glob("*.json"))]
    latest = snaps[-1]
    OUT.mkdir(exist_ok=True)

    weekly = pd.DataFrame(latest["weekly_installs"]).rename(columns={"label": "week", "count": "installs"})
    weekly["week"] = pd.to_datetime(weekly.week)
    weekly["net_adds"] = weekly.installs.diff()
    weekly.to_csv(OUT / "pixel_weekly_installs.csv", index=False)

    hist = history(snaps)
    hist.to_csv(OUT / "pixel_country_history.csv", index=False)

    total = latest["installs"]
    now = pd.Series(latest["countries"]).sort_values(ascending=False)
    print(f"\nAs of {latest['updated']}: {total:,} stores; Shopify {latest['platforms'].get('Shopify', 0) / total:.1%}")
    print(f"APAC share {now[now.index.isin(APAC)].sum() / total:.1%}; HK {now.get('HK', 0) / total:.1%}; "
          f"US {now.get('US', 0) / total:.1%}; unknown {latest['unknown_country'] / total:.1%}")

    # Country growth between the earliest archived count and now.
    weekly_idx = weekly.set_index("week").installs
    then = hist[hist.source == "commoncrawl"]
    growth = []
    for _, r in then.iterrows():
        base_total = weekly_idx.asof(pd.Timestamp(r.as_of))
        growth.append(dict(country=r.country, as_of=r.as_of, stores_then=r.stores,
                           stores_now=latest["countries"].get(r.country, 0),
                           share_then=r.stores / base_total, share_now=latest["countries"].get(r.country, 0) / total))
    growth = pd.DataFrame(growth).sort_values("stores_now", ascending=False)
    growth.to_csv(OUT / "pixel_country_growth.csv", index=False)
    print("\nCountries with an archived count (Common Crawl) vs now:")
    print(growth.to_string(index=False, formatters={"share_then": "{:.2%}".format, "share_now": "{:.2%}".format}))
    plot(weekly, now, total, latest)


def plot(weekly, now, total, latest):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    blue, grey, muted = "#2a78d6", "#b5b4ae", "#52514e"
    plt.rcParams.update({"font.size": 10, "axes.edgecolor": grey, "xtick.color": muted, "ytick.color": muted,
                         "axes.labelcolor": muted, "axes.spines.top": False, "axes.spines.right": False})
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 4.6), gridspec_kw={"width_ratios": [1.6, 1]})
    fig.patch.set_facecolor("#fcfcfb")

    a1.plot(weekly.week, weekly.installs, color=blue, lw=2)
    a1.set_title("Ecommerce stores running the AppLovin AXON Pixel (weekly)", loc="left", fontsize=11)
    a1.grid(axis="y", color="#ecebe7", lw=0.8)
    for d, label in [("2025-10-10", "Oct '25 step-up"), ("2026-09-25", f"{total:,}")]:
        y = weekly.set_index("week").installs.asof(pd.Timestamp(d))
        a1.annotate(label, (pd.Timestamp(d), y), textcoords="offset points", xytext=(-10, 8), ha="right", color=muted)
    a1.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))

    top = now.head(8)
    other = total - top.sum() - latest["unknown_country"]
    names = [pycountry.countries.get(alpha_2=c).name.split(",")[0] for c in top.index] + ["Unknown", "All other"]
    vals = list(top.values) + [latest["unknown_country"], other]
    colors = [blue if c == "HK" else grey for c in top.index] + [grey, grey]
    bars = a2.barh(names[::-1], [v / total * 100 for v in vals][::-1], color=colors[::-1], height=0.6)
    a2.bar_label(bars, labels=[f"{v / total:.1%}" for v in vals][::-1], padding=3, color=muted, fontsize=9)
    a2.set_title(f"Country mix, {latest['updated']}", loc="left", fontsize=11)
    a2.set_xlabel("% of stores")
    a2.set_xlim(0, 60)
    fig.text(0.01, 0.01, "Source: Store Leads free technology report (AppLovin AXON Pixel).", color=muted, fontsize=8)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(OUT / "pixel_installs_country.png", dpi=140, facecolor=fig.get_facecolor())
    print(f"wrote {OUT / 'pixel_installs_country.png'}")


if __name__ == "__main__":
    main()
