"""Turn the exported HTTP Archive panels into the Wells Fargo-style exhibits.

Reads data/base_counts.csv, data/applovin_sites.csv and (optionally)
data/site_region.csv; writes charts and summary tables to output/.
"""

from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parent
DATA, OUT = ROOT / "data", ROOT / "output"

# CrUX rank buckets are upper bounds (top 1k, top 5k, ...). Approximate each
# site's traffic with a Zipf weight 1/rank at the bucket's geometric midpoint.
BUCKETS = [1_000, 5_000, 10_000, 50_000, 100_000, 500_000, 1_000_000,
           5_000_000, 10_000_000, 50_000_000, 100_000_000]


def traffic_weight(rank):
    i = BUCKETS.index(rank) if rank in BUCKETS else len(BUCKETS) - 1
    lo = BUCKETS[i - 1] if i else 1
    return 1.0 / (lo * rank) ** 0.5


def main():
    OUT.mkdir(exist_ok=True)
    base = pd.read_csv(DATA / "base_counts.csv", parse_dates=["date"])
    sites = pd.read_csv(DATA / "applovin_sites.csv", parse_dates=["date", "prev_date"])
    region_path = DATA / "site_region.csv"
    if region_path.exists():
        sites = sites.merge(pd.read_csv(region_path)[["site", "country", "apac"]],
                            on="site", how="left")

    sites["w"] = sites["rank"].map(traffic_weight)
    sites["long_tail"] = sites["rank"] >= 10_000_000
    # An "add" = pixel present this month, site crawled last month without it.
    adds = sites[sites.crawled_prev & ~sites.applovin_prev & sites.prev_date.notna()]
    # Sites that entered the crawl already carrying the pixel (new to CrUX).
    entrants = sites[~sites.crawled_prev & sites.prev_date.notna()]

    g = adds.groupby("date")
    monthly = pd.DataFrame({
        "installed_base": sites.groupby("date").size(),
        "adds": g.size(),
        "new_crawl_entrants_with_pixel": entrants.groupby("date").size(),
        "adds_shopify_pct": g.shopify.mean() * 100,
        "adds_long_tail_pct": g.long_tail.mean() * 100,
        "adds_traffic_weighted": g.w.sum(),
    })
    if "apac" in adds:
        monthly["adds_apac_pct"] = g.apac.mean() * 100
    monthly = monthly.join(base.set_index("date")[["snap", "pinterest", "tiktok", "crawled_sites"]])

    # Index count vs traffic-weighted adds to their 1H26 average (exhibit 4 analogue).
    h1 = monthly.loc["2026-01-01":"2026-06-01"]
    monthly["adds_idx_1h26"] = monthly.adds / h1.adds.mean() * 100
    monthly["weighted_idx_1h26"] = monthly.adds_traffic_weighted / h1.adds_traffic_weighted.mean() * 100
    monthly.round(2).to_csv(OUT / "monthly_summary.csv")
    print(monthly.round(1).to_string())

    fig, ax = plt.subplots(2, 2, figsize=(13, 8))
    monthly[["adds", "new_crawl_entrants_with_pixel"]].plot.bar(ax=ax[0, 0], stacked=True)
    ax[0, 0].set_title("AppLovin pixel adds per month (HTTP Archive)")
    monthly[["installed_base", "snap", "pinterest"]].plot(ax=ax[0, 1], logy=True, marker="o")
    ax[0, 1].set_title("Installed base vs Snap / Pinterest (log)")
    mix = ["adds_shopify_pct", "adds_long_tail_pct"] + (["adds_apac_pct"] if "adds_apac_pct" in monthly else [])
    monthly[mix].plot(ax=ax[1, 0], marker="o")
    ax[1, 0].set_title("Mix of adds (%)")
    monthly[["adds_idx_1h26", "weighted_idx_1h26"]].plot(ax=ax[1, 1], marker="o")
    ax[1, 1].axhline(100, color="grey", lw=0.8)
    ax[1, 1].set_title("Adds: count vs traffic-weighted (1H26 = 100)")
    for a in ax.flat:
        a.set_xlabel("")
        if a is not ax[0, 0]:
            a.tick_params(axis="x", rotation=45)
    ax[0, 0].set_xticklabels([d.strftime("%Y-%m") for d in monthly.index], rotation=45)
    fig.tight_layout()
    fig.savefig(OUT / "exhibits.png", dpi=130)
    print(f"wrote {OUT / 'exhibits.png'}")


if __name__ == "__main__":
    main()
