import os
import re
import smtplib
import ssl
from email.message import EmailMessage


DEFAULT_SMTP_HOST = "smtp.qq.com"
DEFAULT_SMTP_PORT = 465


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _int_env(name: str, default: int) -> int:
    raw_value = _env(name)
    if not raw_value:
        return default
    return int(raw_value)


def _split_recipients(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[;,]", value) if item.strip()]


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}%"


def _build_subject(snapshot: dict) -> str:
    status = "需要再平衡" if snapshot.get("rebalance_needed") else "无需再平衡"
    return f"永久投资组合日报 {snapshot['date']} | {status}"


def _build_body(snapshot: dict, cfg: dict) -> str:
    lines: list[str] = [
        "永久投资组合日报",
        f"日期: {snapshot['date']}",
        f"总资产市值: {snapshot['total_value']:.2f}",
        f"组合总涨跌: {snapshot['total_pnl_pct']:+.2f}%",
        f"再平衡判断: {'需要' if snapshot.get('rebalance_needed') else '不需要'}",
        f"阈值范围: {_fmt_pct(cfg.get('alert_lower', 0) * 100)} ~ {_fmt_pct(cfg.get('alert_upper', 0) * 100)}",
        "",
        "资产大类",
    ]

    current_weights = snapshot.get("asset_class_weights", {})
    target_weights = snapshot.get("target_asset_class_weights", {})
    asset_classes = []
    for asset_class in target_weights:
        if asset_class not in asset_classes:
            asset_classes.append(asset_class)
    for asset_class in current_weights:
        if asset_class not in asset_classes:
            asset_classes.append(asset_class)

    for asset_class in asset_classes:
        current_weight = current_weights.get(asset_class)
        target_weight = target_weights.get(asset_class)
        delta = ""
        if current_weight is not None and target_weight is not None:
            delta = f" | 偏离 {current_weight - target_weight:+.2f}pp"
        lines.append(
            f"- {asset_class}: 当前 {_fmt_pct(current_weight)} | 目标 {_fmt_pct(target_weight)}{delta}"
        )

    if snapshot.get("alerts"):
        lines.extend(["", "再平衡预警"])
        lines.extend(f"- {alert}" for alert in snapshot["alerts"])
    else:
        lines.extend(["", "再平衡结论", "- 当前各大类权重均在阈值范围内。"])

    lines.extend(["", "基金占比"])
    for snap in snapshot["positions"]:
        note = ""
        if snap.get("nav_source") == "fallback":
            note = " | 净值来自上日兜底"
        elif snap.get("nav_source") == "stale":
            note = " | 净值缺失，按买入净值估算"
        lines.append(
            f"- {snap['fund_name']} ({snap['fund_code']}): {snap['weight_pct']:.2f}% | 市值 {snap['market_value']:.2f} | 盈亏 {snap['pnl_pct']:+.2f}%{note}"
        )

    cash = snapshot["cash"]
    lines.append(
        f"- 现金: {cash['weight_pct']:.2f}% | 市值 {cash['market_value']:.2f} | 盈亏 {cash['pnl_pct']:+.2f}%"
    )

    if snapshot.get("has_missing"):
        lines.extend(
            [
                "",
                "数据说明",
                "- 部分基金当日净值缺失，已使用历史净值或买入净值兜底，相关指标仅供参考。",
            ]
        )

    return "\n".join(lines)


def send_email_report(snapshot: dict, cfg: dict) -> bool:
    smtp_user = _env("SMTP_USER") or _env("MAIL_SMTP_USERNAME") or _env("QQ_MAIL_USER")
    smtp_password = _env("SMTP_PASSWORD") or _env("MAIL_SMTP_PASSWORD") or _env("QQ_MAIL_AUTH_CODE")
    recipient_value = _env("EMAIL_TO") or _env("MAIL_TO") or _env("QQ_MAIL_TO") or smtp_user

    if not smtp_user or not smtp_password or not recipient_value:
        print("[INFO] 未配置邮件账号或授权码，跳过发送邮件。")
        return False

    recipients = _split_recipients(recipient_value)
    if not recipients:
        print("[INFO] 未配置有效收件人，跳过发送邮件。")
        return False

    smtp_host = _env("SMTP_HOST") or _env("MAIL_SMTP_HOST") or DEFAULT_SMTP_HOST
    smtp_port = _int_env("SMTP_PORT", _int_env("MAIL_SMTP_PORT", DEFAULT_SMTP_PORT))
    from_addr = _env("EMAIL_FROM") or _env("MAIL_FROM") or smtp_user

    message = EmailMessage()
    message["From"] = from_addr
    message["To"] = ", ".join(recipients)
    message["Subject"] = _build_subject(snapshot)
    message.set_content(_build_body(snapshot, cfg), charset="utf-8")

    context = ssl.create_default_context()
    if smtp_port == 465:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context, timeout=30) as client:
            client.login(smtp_user, smtp_password)
            client.send_message(message)
    else:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as client:
            client.ehlo()
            if _env("MAIL_USE_STARTTLS", "true").lower() in {"1", "true", "yes", "on"}:
                client.starttls(context=context)
                client.ehlo()
            client.login(smtp_user, smtp_password)
            client.send_message(message)

    print(f"\n邮件已发送至: {', '.join(recipients)}")
    return True