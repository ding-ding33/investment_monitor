import yaml
import os

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")


def load_config(path: str = CONFIG_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    cfg.setdefault("initial_principal", 4000)
    cfg.setdefault("cash_value", 1000)
    cfg.setdefault("alert_upper", 0.35)
    cfg.setdefault("alert_lower", 0.15)
    cfg.setdefault("lookback_days", 5)

    total_cost = sum(p["cost_basis"] for p in cfg["positions"]) + cfg["cash_value"]
    if total_cost != cfg["initial_principal"]:
        raise ValueError(
            f"持仓成本合计 {total_cost} 与 initial_principal {cfg['initial_principal']} 不匹配"
        )

    for p in cfg["positions"]:
        if p["cost_basis"] <= 0:
            raise ValueError(f"基金 {p['fund_code']} 成本必须 > 0")
        if "purchase_nav" not in p or p["purchase_nav"] <= 0:
            raise ValueError(f"基金 {p['fund_code']} 缺少 purchase_nav 或值无效")
        # 由买入金额和买入净值反推实际持有份额
        p["shares"] = round(p["cost_basis"] / p["purchase_nav"], 4)

    return cfg
