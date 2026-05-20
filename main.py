"""永久投资组合自动化追踪程序

抓取基金净值 → 计算各项指标 → 持久化 Excel → 输出报告与预警。
"""

import sys
from src.config import load_config
from src.fetcher import fetch_all_navs
from src.calculator import calculate_snapshot
from src.storage import save_snapshot, read_last_navs
from src.reporter import print_report
from src.notifier import send_email_report


def main():
    print("加载配置 ...")
    try:
        cfg = load_config()
    except Exception as e:
        print(f"[ERROR] 配置加载失败: {e}")
        sys.exit(1)

    print(f"共 {len(cfg['positions'])} 支基金 + 现金，本金 {cfg['initial_principal']} 元\n")

    print("抓取基金净值 ...")
    nav_map = fetch_all_navs(cfg["positions"], cfg["lookback_days"])

    missing = [code for code, v in nav_map.items() if v is None]
    fallback_navs = {}
    if missing:
        print(f"\n[INFO] {len(missing)} 支基金今日无净值，尝试从历史表格兜底 ...")
        fallback_navs = read_last_navs()
        for code in missing:
            if code in fallback_navs:
                print(f"  {code} → 使用上日净值 ({fallback_navs[code]['nav_date']})")
            else:
                print(f"  {code} → 无兜底数据，将用买入净值估算（数据缺失）")

    print("\n计算财务指标 ...")
    snapshot = calculate_snapshot(cfg, nav_map, fallback_navs)

    save_snapshot(snapshot)
    print_report(snapshot)

    try:
        send_email_report(snapshot, cfg)
    except Exception as e:
        print(f"[WARN] 邮件发送失败: {e}")


if __name__ == "__main__":
    main()
