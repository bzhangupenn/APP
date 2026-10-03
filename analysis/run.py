"""Rebuild the Wells Fargo AppLovin-pixel analysis from HTTP Archive.

Usage:
    python analysis/run.py --project MY_GCP_PROJECT --dry-run   # cost estimate only
    python analysis/run.py --project MY_GCP_PROJECT             # run + export CSVs

Needs the `bq` CLI authenticated against a project with BigQuery billing.
HTTP Archive is a public dataset; you pay only for bytes scanned.
"""

import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SQL = ROOT / "sql"
DATA = ROOT / "data"


def crawl_dates(start, end):
    d = start
    out = []
    while d <= end:
        out.append(d)
        d = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return out


def render(name, **kw):
    return (SQL / name).read_text().format(**kw)


def bq(args, sql=None):
    cmd = ["bq", "--quiet", *args]
    if sql is not None:
        cmd.append(sql)
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        sys.exit(f"bq failed: {' '.join(args)}\n{res.stdout}\n{res.stderr}")
    return res.stdout


def dry_run_gb(project, sql):
    out = bq([f"--project_id={project}", "query", "--use_legacy_sql=false", "--dry_run"], sql)
    m = re.search(r"process (\d+) bytes", out)
    return int(m.group(1)) / 1e9 if m else float("nan")


def materialize(project, dataset, table, sql, max_gb):
    bq([f"--project_id={project}", "query", "--use_legacy_sql=false",
        f"--destination_table={project}:{dataset}.{table}", "--replace",
        f"--maximum_bytes_billed={int(max_gb * 1e9)}"], sql)


def export_csv(project, sql, path, max_gb):
    out = bq([f"--project_id={project}", "query", "--use_legacy_sql=false",
              "--format=csv", "--max_rows=5000000",
              f"--maximum_bytes_billed={int(max_gb * 1e9)}"], sql)
    path.write_text(out)
    print(f"  wrote {path} ({out.count(chr(10)) - 1} rows)")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--project", required=True)
    p.add_argument("--dataset", default="app_pixel")
    p.add_argument("--start", default="2025-01-01")
    p.add_argument("--end", default=dt.date.today().replace(day=1).isoformat())
    p.add_argument("--max-gb", type=float, default=6000,
                   help="per-query billing cap in GB (~$6.25/TB on-demand)")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    dates = crawl_dates(dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end))
    date_sql = ", ".join(f"DATE '{d}'" for d in dates)
    kw = dict(project=a.project, dataset=a.dataset, dates=date_sql)

    heavy = [("site_month", "01_site_month.sql"), ("crawled", "02_crawled.sql")]
    total = 0.0
    for table, f in heavy:
        gb = dry_run_gb(a.project, render(f, **kw))
        total += gb
        print(f"{f}: {gb:,.0f} GB  (~${gb / 1000 * 6.25:,.2f})")
    print(f"total heavy scan: {total:,.0f} GB (~${total / 1000 * 6.25:,.2f})")
    if a.dry_run:
        return

    bq([f"--project_id={a.project}", "mk", "-f", "--dataset", "--location=US",
        f"{a.project}:{a.dataset}"])
    for table, f in heavy:
        print(f"materializing {table} ...")
        materialize(a.project, a.dataset, table, render(f, **kw), a.max_gb)

    DATA.mkdir(exist_ok=True)
    export_csv(a.project, render("03_base_counts.sql", **kw), DATA / "base_counts.csv", 50)
    export_csv(a.project, render("04_applovin_sites.sql", **kw), DATA / "applovin_sites.csv", 50)


if __name__ == "__main__":
    main()
