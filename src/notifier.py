import os
import html
import re
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


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


def _fmt_money(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}"


def _safe(value: object) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def _build_subject(snapshot: dict) -> str:
    status = "需要再平衡" if snapshot.get("rebalance_needed") else "无需再平衡"
    return f"永久投资组合日报 {snapshot['date']} | {status}"


def _build_body(snapshot: dict, cfg: dict) -> str:
    current_weights = snapshot.get("asset_class_weights", {})
    target_weights = snapshot.get("target_asset_class_weights", {})
    status_text = "需要再平衡" if snapshot.get("rebalance_needed") else "无需再平衡"
    lines: list[str] = [
        "永久投资组合日报（简版）",
        f"日期: {snapshot['date']}",
        f"总资产: {snapshot['total_value']:.2f}",
        f"涨跌: {snapshot['total_pnl_pct']:+.2f}%",
        f"再平衡: {status_text}",
        "",
        "资产大类:"
    ]

    for asset_class in target_weights or current_weights:
        current_weight = current_weights.get(asset_class)
        target_weight = target_weights.get(asset_class)
        lines.append(f"- {asset_class}: { _fmt_pct(current_weight)} / { _fmt_pct(target_weight)}")

    return "\n".join(lines)


def _build_card(label: str, value: str, *, color: str = "#111827") -> str:
    """Build a single summary card as a nested table (email-safe)."""
    return (
        '<table width="100%" cellpadding="0" cellspacing="0" border="0"'
        ' style="background-color:#f9fafb;border-radius:10px;border:1px solid #e5e7eb;">'
        "<tr>"
        f'<td style="padding:12px 14px;">'
        f'<div style="font-size:11px;color:#6b7280;margin-bottom:4px;">{_safe(label)}</div>'
        f'<div style="font-size:18px;font-weight:700;color:{color};word-break:break-word;">{_safe(value)}</div>'
        "</td>"
        "</tr>"
        "</table>"
    )


def _build_html_body(snapshot: dict, cfg: dict) -> str:
    rebalance_needed = bool(snapshot.get("rebalance_needed"))
    status_text = "需要再平衡" if rebalance_needed else "无需再平衡"
    status_color = "#dc2626" if rebalance_needed else "#059669"
    status_bg = "#fef2f2" if rebalance_needed else "#ecfdf3"
    status_border = "#fecaca" if rebalance_needed else "#a7f3d0"

    pnl = snapshot["total_pnl_pct"]
    pnl_color = "#dc2626" if pnl < 0 else "#059669"

    current_weights = snapshot.get("asset_class_weights", {})
    target_weights = snapshot.get("target_asset_class_weights", {})
    asset_classes: list[str] = []
    for asset_class in target_weights:
        if asset_class not in asset_classes:
            asset_classes.append(asset_class)
    for asset_class in current_weights:
        if asset_class not in asset_classes:
            asset_classes.append(asset_class)

    # --- asset allocation rows ---
    asset_rows_parts = []
    for i, asset_class in enumerate(asset_classes):
        current_weight = current_weights.get(asset_class)
        target_weight = target_weights.get(asset_class)
        delta = ""
        delta_color = "#6b7280"
        if current_weight is not None and target_weight is not None:
            d = current_weight - target_weight
            delta = f"{d:+.2f}pp"
            lower = cfg.get("alert_lower", 0)
            upper = cfg.get("alert_upper", 0)
            if d > 0 and current_weight / 100.0 > upper:
                delta_color = "#dc2626"
            elif d < 0 and current_weight / 100.0 < lower:
                delta_color = "#dc2626"
        row_bg = "#f9fafb" if i % 2 == 0 else "#ffffff"
        asset_rows_parts.append(
            f'<tr style="background-color:{row_bg};">'
            f'<td style="padding:10px 8px;border-bottom:1px solid #f3f4f6;font-size:13px;font-weight:600;">{_safe(asset_class)}</td>'
            f'<td style="padding:10px 8px;border-bottom:1px solid #f3f4f6;font-size:13px;text-align:right;">{_fmt_pct(current_weight)}</td>'
            f'<td style="padding:10px 8px;border-bottom:1px solid #f3f4f6;font-size:13px;text-align:right;">{_fmt_pct(target_weight)}</td>'
            f'<td style="padding:10px 8px;border-bottom:1px solid #f3f4f6;font-size:13px;text-align:right;color:{delta_color};">{_safe(delta or "—")}</td>'
            "</tr>"
        )

    # --- position rows ---
    position_rows_parts = []
    for i, snap in enumerate(snapshot["positions"]):
        note = ""
        if snap.get("nav_source") == "fallback":
            note = "兜底"
        elif snap.get("nav_source") == "stale":
            note = "估算"
        note_html = (
            f'<span style="display:inline-block;margin-top:2px;font-size:10px;color:#f59e0b;background:#fffbeb;border:1px solid #fde68a;border-radius:4px;padding:1px 5px;">{_safe(note)}</span>'
            if note
            else ""
        )
        pnl_val = snap["pnl_pct"]
        pnl_td_color = "#dc2626" if pnl_val < 0 else "#059669"
        row_bg = "#f9fafb" if i % 2 == 0 else "#ffffff"
        position_rows_parts.append(
            f'<tr style="background-color:{row_bg};">'
            f'<td style="padding:10px 8px;border-bottom:1px solid #f3f4f6;font-size:13px;">'
            f'<div style="font-weight:600;">{_safe(snap["fund_name"])}</div>'
            f'<div style="font-size:11px;color:#6b7280;margin-top:2px;">{_safe(snap["fund_code"])}</div>'
            f"{note_html}"
            "</td>"
            f'<td style="padding:10px 8px;border-bottom:1px solid #f3f4f6;font-size:13px;text-align:right;">{snap["weight_pct"]:.2f}%</td>'
            f'<td style="padding:10px 8px;border-bottom:1px solid #f3f4f6;font-size:13px;text-align:right;">{_fmt_money(snap["market_value"])}</td>'
            f'<td style="padding:10px 8px;border-bottom:1px solid #f3f4f6;font-size:13px;text-align:right;color:{pnl_td_color};">{snap["pnl_pct"]:+.2f}%</td>'
            "</tr>"
        )

    cash = snapshot["cash"]
    cash_weight_str = f"{cash['weight_pct']:.2f}%"

    # --- summary cards (2x2 grid via nested tables) ---
    summary_html = (
        '<table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:16px 0 6px;">'
        "<tr>"
        f'<td width="50%" style="padding:0 5px 10px 0;" valign="top">{_build_card("总资产市值", _fmt_money(snapshot["total_value"]))}</td>'
        f'<td width="50%" style="padding:0 0 10px 5px;" valign="top">{_build_card("组合总涨跌", f"{pnl:+.2f}%", color=pnl_color)}</td>'
        "</tr>"
        "<tr>"
        f'<td width="50%" style="padding:0 5px 0 0;" valign="top">{_build_card("现金占比", cash_weight_str)}</td>'
        f'<td width="50%" style="padding:0 0 0 5px;" valign="top">{_build_card("再平衡", status_text, color=status_color)}</td>'
        "</tr>"
        "</table>"
    )

    # --- section title helper ---
    def _section_title(title: str) -> str:
        return (
            '<div style="font-size:15px;font-weight:700;color:#111827;margin:18px 0 8px;padding-top:8px;border-top:1px solid #e5e7eb;">'
            f"{_safe(title)}"
            "</div>"
        )

    # --- alert / ok block ---
    if snapshot.get("alerts"):
        alert_items = "".join(
            f'<li style="margin-bottom:4px;">{_safe(a)}</li>' for a in snapshot["alerts"]
        )
        alert_html = (
            _section_title("再平衡预警")
            + f'<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#fef2f2;border-radius:10px;border:1px solid #fecaca;"><tr>'
            f'<td style="padding:12px 14px;font-size:13px;color:#991b1b;line-height:1.6;">'
            f'<ul style="margin:0;padding-left:18px;">{alert_items}</ul>'
            "</td></tr></table>"
        )
    else:
        alert_html = (
            _section_title("再平衡结论")
            + '<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#ecfdf3;border-radius:10px;border:1px solid #a7f3d0;"><tr>'
            '<td style="padding:12px 14px;font-size:13px;color:#065f46;">当前各大类权重均在阈值范围内。</td>'
            "</tr></table>"
        )

    # --- missing data block ---
    missing_html = ""
    if snapshot.get("has_missing"):
        missing_html = (
            _section_title("数据说明")
            + '<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#eff6ff;border-radius:10px;border:1px solid #bfdbfe;"><tr>'
            '<td style="padding:12px 14px;font-size:13px;color:#1e40af;">部分基金当日净值缺失，已使用历史净值或买入净值兜底，指标仅供参考。</td>'
            "</tr></table>"
        )

    # --- assemble ---
    threshold_info = f"阈值 {_fmt_pct(cfg.get('alert_lower', 0) * 100)} ~ {_fmt_pct(cfg.get('alert_upper', 0) * 100)}"

    html_body = (
        '<!DOCTYPE html>'
        '<html>'
        '<head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        "</head>"
        '<body style="margin:0;padding:0;background-color:#f0f2f5;font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',\'PingFang SC\',\'Hiragino Sans GB\',\'Microsoft YaHei\',sans-serif;">'
        '<table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#f0f2f5;">'
        "<tr>"
        '<td align="center" style="padding:16px 8px;">'
        # --- main container ---
        '<table width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;background-color:#ffffff;border-radius:16px;overflow:hidden;">'
        # top accent bar
        '<tr><td style="height:4px;background-color:#6366f1;font-size:0;line-height:0;"></td></tr>'
        # header
        "<tr>"
        f'<td style="padding:20px 20px 12px;">'
        '<table width="100%" cellpadding="0" cellspacing="0" border="0">'
        "<tr>"
        '<td valign="top">'
        '<div style="font-size:20px;font-weight:700;color:#111827;line-height:1.3;">永久投资组合日报</div>'
        f'<div style="font-size:12px;color:#6b7280;margin-top:4px;">日期 {_safe(snapshot["date"])} · {_safe(threshold_info)}</div>'
        "</td>"
        '<td align="right" valign="top">'
        f'<span style="display:inline-block;padding:5px 10px;border-radius:999px;background-color:{status_bg};color:{status_color};border:1px solid {status_border};font-size:12px;font-weight:700;white-space:nowrap;">{_safe(status_text)}</span>'
        "</td>"
        "</tr>"
        "</table>"
        "</td>"
        "</tr>"
        # summary cards
        f"<tr><td>{summary_html}</td></tr>"
        # asset allocation section
        f"<tr><td>{_section_title('资产大类配置')}</td></tr>"
        "<tr>"
        '<td>'
        '<table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">'
        "<thead>"
        "<tr>"
        '<th style="padding:10px 8px;border-bottom:2px solid #e5e7eb;text-align:left;font-size:12px;color:#6b7280;font-weight:600;">资产</th>'
        '<th style="padding:10px 8px;border-bottom:2px solid #e5e7eb;text-align:right;font-size:12px;color:#6b7280;font-weight:600;">当前</th>'
        '<th style="padding:10px 8px;border-bottom:2px solid #e5e7eb;text-align:right;font-size:12px;color:#6b7280;font-weight:600;">目标</th>'
        '<th style="padding:10px 8px;border-bottom:2px solid #e5e7eb;text-align:right;font-size:12px;color:#6b7280;font-weight:600;">偏离</th>'
        "</tr>"
        "</thead>"
        "<tbody>"
        f"{''.join(asset_rows_parts)}"
        "</tbody>"
        "</table>"
        "</td>"
        "</tr>"
        # alerts
        f"<tr><td>{alert_html}</td></tr>"
        # fund positions section
        f"<tr><td>{_section_title('基金占比明细')}</td></tr>"
        "<tr>"
        "<td>"
        '<table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">'
        "<thead>"
        "<tr>"
        '<th style="padding:10px 8px;border-bottom:2px solid #e5e7eb;text-align:left;font-size:12px;color:#6b7280;font-weight:600;">基金</th>'
        '<th style="padding:10px 8px;border-bottom:2px solid #e5e7eb;text-align:right;font-size:12px;color:#6b7280;font-weight:600;">占比</th>'
        '<th style="padding:10px 8px;border-bottom:2px solid #e5e7eb;text-align:right;font-size:12px;color:#6b7280;font-weight:600;">市值</th>'
        '<th style="padding:10px 8px;border-bottom:2px solid #e5e7eb;text-align:right;font-size:12px;color:#6b7280;font-weight:600;">盈亏</th>'
        "</tr>"
        "</thead>"
        "<tbody>"
        f"{''.join(position_rows_parts)}"
        # cash row
        f'<tr style="background-color:#f9fafb;">'
        f'<td style="padding:10px 8px;border-bottom:1px solid #f3f4f6;font-size:13px;">'
        f'<div style="font-weight:600;">现金</div>'
        f'<div style="font-size:11px;color:#6b7280;margin-top:2px;">CASH</div>'
        "</td>"
        f'<td style="padding:10px 8px;border-bottom:1px solid #f3f4f6;font-size:13px;text-align:right;">{cash["weight_pct"]:.2f}%</td>'
        f'<td style="padding:10px 8px;border-bottom:1px solid #f3f4f6;font-size:13px;text-align:right;">{_fmt_money(cash["market_value"])}</td>'
        f'<td style="padding:10px 8px;border-bottom:1px solid #f3f4f6;font-size:13px;text-align:right;">{cash["pnl_pct"]:+.2f}%</td>'
        "</tr>"
        "</tbody>"
        "</table>"
        "</td>"
        "</tr>"
        # missing data note
        f"<tr><td>{missing_html}</td></tr>"
        # footer
        "<tr>"
        '<td style="padding:16px 20px;border-top:1px solid #e5e7eb;">'
        '<div style="font-size:11px;color:#9ca3af;text-align:center;">自动生成 · 永久投资组合追踪系统</div>'
        "</td>"
        "</tr>"
        "</table>"
        # --- end main container ---
        "</td>"
        "</tr>"
        "</table>"
        "</body>"
        "</html>"
    )

    return html_body


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

    print(
        f"[INFO] 准备发送邮件: host={smtp_host}, port={smtp_port}, from={from_addr}, to={', '.join(recipients)}"
    )

    message = MIMEMultipart("alternative")
    message["From"] = from_addr
    message["To"] = ", ".join(recipients)
    message["Subject"] = _build_subject(snapshot)
    message.attach(MIMEText(_build_body(snapshot, cfg), "plain", "utf-8"))
    message.attach(MIMEText(_build_html_body(snapshot, cfg), "html", "utf-8"))

    context = ssl.create_default_context()
    try:
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
    except (smtplib.SMTPException, OSError) as exc:
        print(f"[ERROR] 邮件发送失败: {exc.__class__.__name__}: {exc}")
        raise

    print(f"\n邮件已发送至: {', '.join(recipients)}")
    return True