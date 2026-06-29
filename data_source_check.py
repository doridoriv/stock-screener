import json

import krx_client
import opendart_client
import finnhub_client
from secret_utils import get_secret


def _present(name: str) -> str:
    return "yes" if get_secret(name) else "no"


def _compact_krx_result(result: dict) -> dict:
    rows = result.get("rows") or []
    sample = rows[0] if rows else {}
    return {
        "ok": result.get("ok"),
        "endpoint": result.get("endpoint"),
        "basDd": result.get("basDd"),
        "row_count": len(rows),
        "columns": result.get("columns", [])[:12],
        "sample": {k: sample.get(k) for k in list(sample.keys())[:8]},
        "reason": result.get("reason"),
        "status_code": result.get("status_code"),
    }


def _compact_dart_result(result: dict) -> dict:
    accounts = result.get("accounts") or []
    return {
        "ok": result.get("ok"),
        "stock_code": result.get("stock_code"),
        "year": result.get("year"),
        "fs_div": result.get("fs_div"),
        "metrics": result.get("metrics"),
        "account_count": len(accounts),
        "accounts": accounts[:15],
        "reason": result.get("reason"),
    }


def main():
    print("[secret-present]")
    for name in ["DART_API_KEY", "KRX_API_KEY", "SERPAPI_KEY", "FINNHUB_API_KEY"]:
        print(f"{name}: {_present(name)}")

    print("\n[krx-openapi-check]")
    for endpoint in ["KOSPI_DAILY", "KOSDAQ_DAILY", "KOSPI_BASE", "KOSDAQ_BASE"]:
        result = krx_client.first_available_daily(endpoint)
        print(json.dumps(_compact_krx_result(result), ensure_ascii=False, default=str))

    print("\n[opendart-account-check]")
    for stock_code in ["005930", "000660", "196170"]:
        result = opendart_client.debug_dart_accounts(stock_code, limit=30)
        print(json.dumps(_compact_dart_result(result), ensure_ascii=False, default=str))

    print("\n[finnhub-check]")
    for symbol in ["AAPL", "MSFT"]:
        metrics = finnhub_client.fetch_finnhub_metrics(symbol)
        compact = {key: metrics.get(key) for key in [
            "analyst_buy_ratio",
            "consensus_revision",
            "target_mean",
            "earnings_surprise_pct",
            "finnhub_source",
        ]}
        print(json.dumps({"symbol": symbol, "metrics": compact}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
