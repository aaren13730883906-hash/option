#!/usr/bin/env python3
"""Extract requested option 1m bars from full local monthly archives.

Source archives are expected under:
  data/科创板 1 分钟数据（全）/华夏上证科创板50ETF/YYYY-MM.zip
  data/创业板 1 分钟数据（全）/易方达创业板ETF/YYYY-MM.zip

Each archive member is one contract CSV, such as SSE.10009848.csv or
SZSE.90005721.csv.  This script writes strategy-compatible cache files:
  data/intraday_cache/YYYY-MM-DD_########_1m.csv
"""

from __future__ import annotations

import argparse
import csv
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RESEARCH = ROOT / "research"
INTRADAY_CACHE = DATA / "intraday_cache"

ARCHIVE_ROOTS = {
    "588000": DATA / "科创板 1 分钟数据（全）" / "华夏上证科创板50ETF",
    "159915": DATA / "创业板 1 分钟数据（全）" / "易方达创业板ETF",
}
PREFIX = {
    "588000": "SSE",
    "159915": "SZSE",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--requirements",
        type=Path,
        default=RESEARCH / "full_option_cache_requirements_202306_202606.csv",
    )
    parser.add_argument("--cache-dir", type=Path, default=INTRADAY_CACHE)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--limit-months", type=int, default=0)
    parser.add_argument(
        "--summary",
        type=Path,
        default=RESEARCH / "full_option_1m_cache_extract_summary.csv",
    )
    return parser.parse_args()


def normalize_code(value: object) -> str:
    digits = "".join(ch for ch in str(value).split(".")[0] if ch.isdigit())
    return digits.zfill(8) if digits else ""


def load_requirements(path: Path) -> pd.DataFrame:
    req = pd.read_csv(path, dtype={"option_code": str, "underlying_code": str})
    if req.empty:
        return req
    req["trade_date"] = pd.to_datetime(req["trade_date"]).dt.strftime("%Y-%m-%d")
    req["underlying_code"] = req["underlying_code"].astype(str).str.split(".").str[0]
    req["option_code"] = req["option_code"].map(normalize_code)
    return req.drop_duplicates(["trade_date", "underlying_code", "option_code"])


def archive_path(underlying: str, ym: str) -> Path:
    return ARCHIVE_ROOTS[underlying] / f"{ym}.zip"


def member_name(underlying: str, option_code: str) -> str:
    return f"{PREFIX[underlying]}.{option_code}.csv"


def standardize_frame(raw: pd.DataFrame, option_code: str, trade_date: str) -> pd.DataFrame:
    if raw.empty:
        return raw
    out = raw.rename(columns={"changeRatio": "change_ratio"}).copy()
    out["datetime"] = pd.to_datetime(out["datetime"], errors="coerce")
    out = out[out["datetime"].dt.strftime("%Y-%m-%d") == trade_date].copy()
    if out.empty:
        return out
    out["option_code"] = option_code
    for col in ["open", "high", "low", "close", "volume", "amount", "change_ratio"]:
        if col not in out:
            out[col] = 0.0 if col in {"volume", "amount"} else pd.NA
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out["amount"] = out["amount"].fillna(0.0)
    out["volume"] = out["volume"].fillna(0.0)
    keep = ["datetime", "option_code", "open", "high", "low", "close", "volume", "amount", "change_ratio"]
    out = out[keep].dropna(subset=["datetime", "close"])
    return out.drop_duplicates(["datetime", "option_code"], keep="last").sort_values("datetime")


def extract_month(
    underlying: str,
    ym: str,
    code_dates: dict[str, set[str]],
    cache_dir: Path,
    overwrite: bool,
) -> dict[str, Any]:
    path = archive_path(underlying, ym)
    requested_files = sum(len(dates) for dates in code_dates.values())
    existing = 0
    written = 0
    missing_member = 0
    empty = 0
    if not path.exists():
        return {
            "underlying_code": underlying,
            "month": ym,
            "archive": str(path),
            "requested_codes": len(code_dates),
            "requested_files": requested_files,
            "written_files": 0,
            "existing_files": 0,
            "missing_members": len(code_dates),
            "empty_files": requested_files,
            "archive_exists": False,
        }

    cache_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        for code, dates in sorted(code_dates.items()):
            member = member_name(underlying, code)
            if member not in names:
                missing_member += 1
                empty += len(dates)
                continue
            with zf.open(member) as fh:
                raw = pd.read_csv(fh)
            for trade_date in sorted(dates):
                out_path = cache_dir / f"{trade_date}_{code}_1m.csv"
                if out_path.exists() and not overwrite:
                    existing += 1
                    continue
                frame = standardize_frame(raw, code, trade_date)
                if frame.empty:
                    empty += 1
                    continue
                frame.to_csv(out_path, index=False, quoting=csv.QUOTE_MINIMAL)
                written += 1

    return {
        "underlying_code": underlying,
        "month": ym,
        "archive": str(path),
        "requested_codes": len(code_dates),
        "requested_files": requested_files,
        "written_files": written,
        "existing_files": existing,
        "missing_members": missing_member,
        "empty_files": empty,
        "archive_exists": True,
    }


def main() -> None:
    args = parse_args()
    req = load_requirements(args.requirements)
    tasks: dict[tuple[str, str], dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for row in req.itertuples(index=False):
        ym = str(row.trade_date)[:7]
        tasks[(str(row.underlying_code), ym)][str(row.option_code)].add(str(row.trade_date))
    items = sorted(tasks.items())
    if args.limit_months > 0:
        items = items[: args.limit_months]

    summaries: list[dict[str, Any]] = []
    for (underlying, ym), code_dates in items:
        stats = extract_month(underlying, ym, code_dates, args.cache_dir, args.overwrite)
        summaries.append(stats)
        print(stats, flush=True)

    summary = pd.DataFrame(summaries)
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.summary, index=False)
    if summary.empty:
        print("no tasks")
    else:
        totals = {
            "months": int(len(summary)),
            "requested_files": int(summary["requested_files"].sum()),
            "written_files": int(summary["written_files"].sum()),
            "existing_files": int(summary["existing_files"].sum()),
            "missing_members": int(summary["missing_members"].sum()),
            "empty_files": int(summary["empty_files"].sum()),
        }
        print(totals)
        print({"summary": str(args.summary)})


if __name__ == "__main__":
    main()
