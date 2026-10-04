"""Check the Wells Fargo pixel claims against Store Leads' free AppLovin report.

Store Leads (storeleads.app) tracks app installs across ~3.1M live Shopify
stores and publishes a free weekly report per app. Each run saves a dated
snapshot to data/storeleads/ so the series can be extended over time, then
compares it with WF's numbers and draws output/storeleads.png.

Usage: python analysis/storeleads.py [--offline]   # --offline reuses saved snapshots
"""

import argparse
import datetime as dt
import html
import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SNAP = ROOT / "data" / "storeleads"
OUT = ROOT / "output"
BASE = "https://storeleads.app/reports/shopify"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")


def text(page):
    page = re.sub(r"<script.*?</script>", " ", page, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))


def table(t, header):
    """Parse a 'Country Stores Name (CC) 1,234 ...' style table after `header`."""
    m = re.search(re.escape(header) + r"(.*?)With a paid account", t)
    rows = re.findall(r"([A-Z][A-Za-z .&]+?)(?: \(([A-Z]{2})\))? ([\d,]+)", m.group(1)) if m else []
    return [{"name": n.strip(), "code": c or None, "stores": int(s.replace(",", ""))} for n, c, s in rows]


def installs_and_countries(page):
    t = text(page)
    return {"installs": int(re.search(r"currently installed on ([\d,]+)", t).group(1).replace(",", "")),
            "countries": table(t, "Country Stores")}


def parse_app(page):
    t = text(page)
    recent = re.search(r"installed AppLovin most recently\. Name Domain Rank Installed (.*?) Top Categories", t)
    return {
        "updated": re.search(r"Updated (\w+ \d+ \d{4})", t).group(1),
        "installs": int(re.search(r"currently installed on ([\d,]+)", t).group(1).replace(",", "")),
        "weekly_installs": json.loads(re.search(r"installData = (\[.*?\]);", page).group(1)),
        "countries": table(t, "Country Stores"),
        "recent_installs": [
            {"domain": d, "rank": int(r.replace(",", "")), "installed": i}
            for d, r, i in re.findall(r"(\S+\.\S+) ([\d,]+) (\d{4}/\d{2}/\d{2})", recent.group(1) if recent else "")
        ],
    }


def snapshot():
    SNAP.mkdir(parents=True, exist_ok=True)
    data = {
        "fetched": dt.date.today().isoformat(),
        "applovin": parse_app(get(f"{BASE}/app/applovin")),
        # Baselines: another ads app with public country data, and all of Shopify.
        "google_youtube": installs_and_countries(get(f"{BASE}/app/google")),
    }
    shopify = text(get(BASE))
    data["all_shopify"] = {
        "live_stores": int(re.search(r"there are ([\d,]+) live stores", shopify).group(1).replace(",", "")),
        "countries": table(shopify, "Country Stores"),
    }
    path = SNAP / f"{data['fetched']}.json"
    path.write_text(json.dumps(data, indent=2))
    print(f"saved {path}")
    return data


def share(countries, code, total=None):
    total = total or sum(c["stores"] for c in countries)
    hit = next((c["stores"] for c in countries if c["code"] == code or c["name"] == "Hong Kong"), None)
    return hit, total


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--offline", action="store_true")
    a = p.parse_args()
    data = (json.loads(sorted(SNAP.glob("20*.json"))[-1].read_text()) if a.offline else snapshot())

    al = data["applovin"]
    weeks = al["weekly_installs"]
    adds = [(w["label"], w["count"] - prev["count"]) for prev, w in zip(weeks, weeks[1:])]
    early = [n for _, n in adds[:-2]]

    hk_al = share(al["countries"], "HK", al["installs"])[0]
    g = data["google_youtube"]
    hk_google = share(g["countries"], "HK")[0] / g["installs"]
    lowest_top10 = min(c["stores"] for c in data["all_shopify"]["countries"])
    live = data["all_shopify"]["live_stores"]

    print(f"\nStore Leads AppLovin report (updated {al['updated']}): {al['installs']:,} Shopify installs")
    print("week ending   installs   net adds")
    for w, (lbl, n) in zip(weeks[1:], adds):
        print(f"  {lbl}   {w['count']:>7,}   {n:>+6,}")
    print(f"avg weekly adds before last 2 weeks: {sum(early) / len(early):,.0f}  (WF: ~220/wk Jun-Aug)")
    print(f"last two weeks: {adds[-2][1]:,} / {adds[-1][1]:,}  (WF: 750 / 1,600)")
    print(f"\nHong Kong share of AppLovin installs: {hk_al / al['installs']:.1%} ({hk_al:,} stores)")
    print(f"Hong Kong share of Google & YouTube app installs: {hk_google:.1%}")
    print(f"Hong Kong share of all live Shopify stores: < {lowest_top10 / live:.1%} (not in top 10; #10 has {lowest_top10:,})")

    # How many of the latest six weeks' adds must be HK, given the HK share of
    # the starting base? Bound it with generous assumptions for that share.
    start, end = weeks[0]["count"], weeks[-1]["count"]
    print(f"\nadds {weeks[0]['label']} -> {weeks[-1]['label']}: {end - start:,}")
    for base_share in (0.02, 0.10, 0.20):
        hk_added = hk_al - base_share * start
        print(f"  if HK was {base_share:.0%} of the {start:,} base -> HK = {hk_added / (end - start):.0%} of adds")
    ranks = [r["rank"] for r in al["recent_installs"]]
    print(f"\nmost recent installs' store ranks: {', '.join(f'{r:,}' for r in ranks)}")
    plot(adds, al, hk_al, hk_google, lowest_top10 / live)


def plot(adds, al, hk_al, hk_google, hk_shopify_max):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    blue, grey, ink, muted = "#2a78d6", "#b5b4ae", "#0b0b0b", "#52514e"
    plt.rcParams.update({"font.size": 10, "axes.edgecolor": grey, "axes.labelcolor": muted,
                         "xtick.color": muted, "ytick.color": muted, "text.color": ink,
                         "axes.spines.top": False, "axes.spines.right": False})
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4.4), gridspec_kw={"width_ratios": [1.4, 1]})
    fig.patch.set_facecolor("#fcfcfb")

    labels = [l[5:] for l, _ in adds]
    vals = [n for _, n in adds]
    colors = [grey] * (len(vals) - 2) + [blue, blue]
    bars = a1.bar(labels, vals, color=colors, width=0.6)
    a1.bar_label(bars, labels=[f"{v:,}" for v in vals], padding=3, color=muted, fontsize=9)
    a1.axhline(220, color=muted, lw=1, ls="--")
    a1.text(-0.4, max(vals) * 0.92, "dashed line: WF's ~220/wk (Jun–Aug)", color=muted, fontsize=9)
    a1.set_title("AppLovin Shopify app: net new installs per week", loc="left", fontsize=11)
    a1.set_xlabel("week ending (2026)")
    a1.grid(axis="y", color="#ecebe7", lw=0.8)
    a1.set_axisbelow(True)

    names = ["All live Shopify\nstores (upper bound)", "Google & YouTube\napp", "AppLovin\napp"]
    vals2 = [hk_shopify_max * 100, hk_google * 100, hk_al / al["installs"] * 100]
    bars2 = a2.barh(names, vals2, color=[grey, grey, blue], height=0.55)
    a2.bar_label(bars2, labels=[f"<{vals2[0]:.1f}%", f"{vals2[1]:.1f}%", f"{vals2[2]:.1f}%"], padding=4, color=muted)
    a2.set_title("Share of stores located in Hong Kong", loc="left", fontsize=11)
    a2.set_xlim(0, 32)
    a2.set_xlabel("% of stores")
    fig.text(0.01, 0.01, f"Source: Store Leads free app reports, updated {al['updated']}.", color=muted, fontsize=8)
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / "storeleads.png", dpi=140, facecolor=fig.get_facecolor())
    print(f"wrote {OUT / 'storeleads.png'}")


if __name__ == "__main__":
    main()
