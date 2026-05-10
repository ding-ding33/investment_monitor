import unicodedata


def _display_width(text: str) -> int:
    width = 0
    for ch in text:
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width


def _truncate_to_width(text: str, max_width: int) -> str:
    if _display_width(text) <= max_width:
        return text
    if max_width <= 3:
        return "." * max_width

    result = []
    current = 0
    for ch in text:
        ch_width = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if current + ch_width > max_width - 3:
            break
        result.append(ch)
        current += ch_width
    return "".join(result) + "..."


def _pad(text: str, width: int, align: str = "left") -> str:
    text = _truncate_to_width(str(text), width)
    pad_size = max(width - _display_width(text), 0)
    if align == "right":
        return (" " * pad_size) + text
    return text + (" " * pad_size)


def print_report(snapshot: dict):
    """控制台输出当日汇总表格和预警信息。"""
    columns = [
        ("资产类别", 10, "left"),
        ("基金名称", 20, "left"),
        ("净值", 10, "right"),
        ("净值日", 12, "left"),
        ("市值", 12, "right"),
        ("盈亏%", 10, "right"),
        ("权重%", 9, "right"),
        ("标记", 4, "left"),
    ]
    sep = " | "
    table_width = sum(w for _, w, _ in columns) + len(sep) * (len(columns) - 1)

    def _row(values: list[str]) -> str:
        return sep.join(
            _pad(value, columns[i][1], columns[i][2]) for i, value in enumerate(values)
        )

    print()
    print("=" * table_width)
    print(f"  永久投资组合 — 日度报告  ({snapshot['date']})")
    print("=" * table_width)

    print(_row([title for title, _, _ in columns]))
    print("-" * table_width)

    for snap in snapshot["positions"] + [snapshot["cash"]]:
        nav_str = f"{snap['nav']:.4f}" if snap["nav"] is not None else "—"
        nav_date_str = snap["nav_date"] or "—"
        source = snap.get("nav_source", "live")
        if source == "fallback":
            mark = "*"
        elif source == "stale":
            mark = "!"
        else:
            mark = ""

        print(_row([
            snap["asset_class"],
            snap["fund_name"],
            nav_str,
            nav_date_str,
            f"{snap['market_value']:.2f}",
            f"{snap['pnl_pct']:+.2f}%",
            f"{snap['weight_pct']:.2f}%",
            mark,
        ]))

    print("-" * table_width)
    print(f"  {'总资产市值:':<30} {snapshot['total_value']:>10.2f}")
    print(f"  {'组合总涨跌:':<30} {snapshot['total_pnl_pct']:>+10.2f}%")
    current_weights = snapshot.get("asset_class_weights", {})
    target_weights = snapshot.get("target_asset_class_weights", {})
    if current_weights:
        current_str = " / ".join(f"{k}:{v:.2f}%" for k, v in current_weights.items())
        print(f"  {'当前大类权重:':<30} {current_str}")
    if target_weights:
        target_str = " / ".join(f"{k}:{v:.2f}%" for k, v in target_weights.items())
        print(f"  {'目标大类权重:':<30} {target_str}")
    print("=" * table_width)

    if snapshot.get("has_missing"):
        print("  ! 标注表示 API 和历史表格均无净值数据，已用买入净值估算，指标仅供参考")
    elif any(p.get("nav_source") == "fallback" for p in snapshot["positions"]):
        print("  * 标注表示当日无最新净值，已使用上日历史净值兜底")

    if snapshot["alerts"]:
        print()
        print("!" * table_width)
        print("  [REBALANCE ALERT] 再平衡预警")
        print("!" * table_width)
        for alert in snapshot["alerts"]:
            print(f"  - {alert}")
        print("!" * table_width)
    else:
        print("  ✓ 各资产权重均在合理范围内，无需再平衡。")

    print()
