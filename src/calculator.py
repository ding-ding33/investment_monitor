def calculate_snapshot(
    cfg: dict,
    nav_map: dict[str, dict | None],
    fallback_nav_map: dict[str, dict | None] | None = None,
) -> dict:
    """根据配置和净值数据，计算完整快照。

    Args:
        cfg: 配置 dict
        nav_map: {fund_code: {"nav": float, "nav_date": str} | None}
        fallback_nav_map: 兜底上日净值，相同结构

    Returns:
        {
            "date": str,
            "positions": [{
                "asset_class": str, "fund_code": str, "fund_name": str,
                "shares": float, "nav": float|None, "nav_date": str|None,
                "market_value": float, "cost_basis": float,
                "pnl_pct": float, "weight_pct": float,
                "is_fallback": bool,
            }, ...],
            "cash": {...},
            "total_value": float,
            "total_pnl_pct": float,
            "alerts": [str, ...],
        }
    """
    fb = fallback_nav_map or {}

    position_snapshots = []
    total_market_value = 0.0
    has_missing = False
    market_by_asset_class: dict[str, float] = {}

    for p in cfg["positions"]:
        code = p["fund_code"]
        nav_info = nav_map.get(code)
        nav_source = "live"

        if nav_info is None and code in fb:
            nav_info = fb[code]
            nav_source = "fallback"

        if nav_info is not None:
            nav = nav_info["nav"]
            nav_date = nav_info["nav_date"]
            market_value = p["shares"] * nav
        else:
            # API 和历史表格都无数据，用买入净值兜底估算
            nav = None
            nav_date = None
            nav_source = "stale"
            market_value = p["shares"] * p["purchase_nav"]
            has_missing = True

        pnl_pct = ((market_value - p["cost_basis"]) / p["cost_basis"]) * 100
        total_market_value += market_value
        market_by_asset_class[p["asset_class"]] = (
            market_by_asset_class.get(p["asset_class"], 0.0) + market_value
        )

        position_snapshots.append({
            "asset_class": p["asset_class"],
            "fund_code": code,
            "fund_name": p["fund_name"],
            "shares": p["shares"],
            "nav": nav,
            "nav_date": nav_date,
            "market_value": round(market_value, 2),
            "cost_basis": p["cost_basis"],
            "pnl_pct": round(pnl_pct, 2),
            "weight_pct": 0.0,
            "nav_source": nav_source,
        })

    total_market_value += cfg["cash_value"]
    cash_pnl_pct = ((cfg["cash_value"] - cfg["cash_value"]) / cfg["cash_value"]) * 100

    cash_snapshot = {
        "asset_class": "现金",
        "fund_code": "CASH",
        "fund_name": "现金",
        "shares": 1.0,
        "nav": None,
        "nav_date": None,
        "market_value": float(cfg["cash_value"]),
        "cost_basis": cfg["cash_value"],
        "pnl_pct": round(cash_pnl_pct, 2),
        "weight_pct": 0.0,
        "nav_source": "live",
    }
    market_by_asset_class["现金"] = market_by_asset_class.get("现金", 0.0) + float(cfg["cash_value"])

    total_pnl_pct = (
        (total_market_value - cfg["initial_principal"]) / cfg["initial_principal"] * 100
    )

    # 计算权重
    for snap in position_snapshots:
        snap["weight_pct"] = round(snap["market_value"] / total_market_value * 100, 2)

    cash_snapshot["weight_pct"] = round(
        cash_snapshot["market_value"] / total_market_value * 100, 2
    )

    # 按资产大类汇总当前权重（避免股票拆分为多只基金后触发单基金误报）
    asset_class_weights = {}
    for asset_class, mv in market_by_asset_class.items():
        asset_class_weights[asset_class] = round(mv / total_market_value * 100, 2)

    # 按成本计算目标权重（与配置保持一致）
    target_cost_by_asset_class: dict[str, float] = {}
    for p in cfg["positions"]:
        target_cost_by_asset_class[p["asset_class"]] = (
            target_cost_by_asset_class.get(p["asset_class"], 0.0) + p["cost_basis"]
        )
    target_cost_by_asset_class["现金"] = (
        target_cost_by_asset_class.get("现金", 0.0) + cfg["cash_value"]
    )
    target_asset_class_weights = {}
    for asset_class, cost in target_cost_by_asset_class.items():
        target_asset_class_weights[asset_class] = round(
            cost / cfg["initial_principal"] * 100, 2
        )

    # 预警检查（按资产大类）
    alerts = []
    for asset_class, weight_pct in asset_class_weights.items():
        w = weight_pct / 100.0
        if w > cfg["alert_upper"]:
            alerts.append(
                f"{asset_class} 类资产权重 {weight_pct}% 超过上限 {cfg['alert_upper']*100}%"
            )
        elif w < cfg["alert_lower"]:
            alerts.append(
                f"{asset_class} 类资产权重 {weight_pct}% 低于下限 {cfg['alert_lower']*100}%"
            )

    return {
        "date": __import__("datetime").date.today().isoformat(),
        "positions": position_snapshots,
        "cash": cash_snapshot,
        "total_value": round(total_market_value, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "alerts": alerts,
        "has_missing": has_missing,
        "asset_class_weights": asset_class_weights,
        "target_asset_class_weights": target_asset_class_weights,
    }
