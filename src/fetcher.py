import akshare as ak
import pandas as pd
from datetime import date, timedelta


def fetch_nav(fund_code: str, lookback_days: int = 5) -> dict | None:
    """获取基金最新单位净值，支持回溯 N 个自然日。

    Returns:
        dict: {"nav": float, "nav_date": str}  或  None（完全获取不到）
    """
    try:
        # AkShare 新版参数名为 symbol；旧版曾使用 fund。
        # 优先走新版参数，避免升级后净值抓取全部失败。
        df: pd.DataFrame = ak.fund_open_fund_info_em(
            symbol=fund_code,
            indicator="单位净值走势",
        )
    except Exception as e:
        print(f"  [WARN] AkShare 请求失败 ({fund_code}): {e}")
        return None

    if df is None or df.empty:
        print(f"  [WARN] 基金 {fund_code} 返回空数据")
        return None

    # 列名通常为 ["净值日期", "单位净值"]
    col_date = df.columns[0]
    col_nav = df.columns[1]

    df[col_date] = pd.to_datetime(df[col_date], errors="coerce")
    df = df.dropna(subset=[col_date, col_nav])
    df = df.sort_values(col_date, ascending=False)

    cutoff = date.today() + timedelta(days=1)

    for _, row in df.iterrows():
        nav_date = row[col_date].date()
        nav_value = float(row[col_nav])
        if nav_date <= cutoff and (cutoff - nav_date).days <= lookback_days:
            return {"nav": nav_value, "nav_date": nav_date.isoformat()}

    print(f"  [WARN] 基金 {fund_code} 在 {lookback_days} 天内无有效净值")
    return None


def fetch_all_navs(positions: list[dict], lookback_days: int) -> dict[str, dict | None]:
    """批量抓取净值，返回 {fund_code: nav_info} 映射。"""
    result = {}
    for p in positions:
        code = p["fund_code"]
        print(f"  抓取 {code} ({p['fund_name']}) ...")
        result[code] = fetch_nav(code, lookback_days)
    return result
