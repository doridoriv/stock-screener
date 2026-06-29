import os
from typing import Iterable

import pandas as pd

from config import CACHE_DIR


SUPPLEMENTAL_FILE = os.path.join(CACHE_DIR, "supplemental_metrics.csv")

SUPPLEMENTAL_FIELDS = [
    "free_cashflow",
    "operating_cashflow",
    "cash",
    "total_debt",
    "net_cash",
    "operating_margin",
    "net_margin",
    "dividend_yield",
    "payout_ratio",
    "dividend_per_share",
    "dividend_total",
    "foreign_net_buy",
    "institution_net_buy",
    "consensus_revision",
    "peer_per_gap",
]


def _normalise_symbol(value):
    if pd.isna(value):
        return ""
    value = str(value).strip()
    if value.endswith(".KS") or value.endswith(".KQ"):
        value = value.split(".")[0]
    return value.zfill(6) if value.isdigit() and len(value) <= 6 else value


def ensure_template(path=SUPPLEMENTAL_FILE):
    if os.path.exists(path):
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cols = ["market", "symbol", "yf_symbol", "data_date", "source"] + SUPPLEMENTAL_FIELDS
    pd.DataFrame(columns=cols).to_csv(path, index=False, encoding="utf-8-sig")


def merge_supplemental_metrics(df: pd.DataFrame, market_text: str, path=SUPPLEMENTAL_FILE) -> pd.DataFrame:
    ensure_template(path)
    try:
        supplemental = pd.read_csv(path)
    except Exception:
        return df

    if supplemental.empty:
        return df

    supplemental = supplemental.copy()
    if "symbol" not in supplemental.columns:
        supplemental["symbol"] = ""
    if "yf_symbol" not in supplemental.columns:
        supplemental["yf_symbol"] = ""
    if "market" not in supplemental.columns:
        supplemental["market"] = market_text

    supplemental["symbol_key"] = supplemental["symbol"].apply(_normalise_symbol)
    supplemental["yf_key"] = supplemental["yf_symbol"].apply(_normalise_symbol)
    market_mask = supplemental["market"].fillna(market_text).astype(str).isin([market_text, "전체", "ALL", ""])
    supplemental = supplemental[market_mask]
    if supplemental.empty:
        return df

    out = df.copy()
    out["symbol_key"] = out["symbol"].apply(_normalise_symbol)
    out["yf_key"] = out["yf_symbol"].apply(_normalise_symbol)

    value_fields = [field for field in SUPPLEMENTAL_FIELDS if field in supplemental.columns]
    meta_fields = [field for field in ["data_date", "source"] if field in supplemental.columns]
    fields = value_fields + meta_fields

    by_symbol = supplemental.dropna(subset=["symbol_key"]).drop_duplicates("symbol_key", keep="last")
    by_yf = supplemental.dropna(subset=["yf_key"]).drop_duplicates("yf_key", keep="last")
    by_symbol_map = {row["symbol_key"]: row for _, row in by_symbol.iterrows() if row["symbol_key"]}
    by_yf_map = {row["yf_key"]: row for _, row in by_yf.iterrows() if row["yf_key"]}

    for idx, row in out.iterrows():
        matched = None
        symbol_key = row["symbol_key"]
        yf_key = row["yf_key"]
        if symbol_key in by_symbol_map:
            matched = by_symbol_map[symbol_key]
        elif yf_key in by_yf_map:
            matched = by_yf_map[yf_key]

        if matched is None:
            continue

        for field in fields:
            val = matched.get(field)
            if pd.isna(val) or str(val).strip() == "":
                continue
            target_field = field
            if field == "source":
                target_field = "supplemental_source"
            elif field == "data_date":
                target_field = "supplemental_date"
            current = out.at[idx, target_field] if target_field in out.columns else None
            if target_field not in out.columns or pd.isna(current) or str(current).strip() in ["", "-", "None", "nan"]:
                out.at[idx, target_field] = val

    return out.drop(columns=["symbol_key", "yf_key"], errors="ignore")


def missing_fields_for(symbol_row: dict, fields: Iterable[str] = SUPPLEMENTAL_FIELDS):
    missing = []
    for field in fields:
        value = symbol_row.get(field)
        if pd.isna(value) or str(value).strip() in ["", "-", "None", "nan"]:
            missing.append(field)
    return missing
