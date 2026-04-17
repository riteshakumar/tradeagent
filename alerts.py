"""
Alert / notification system.
Supports: Email (SMTP), Slack webhook, Telegram bot.
Configure via .env — only enabled channels fire.
"""
import smtplib
import json
import logging
import requests
from email.mime.text import MIMEText
import config

log = logging.getLogger(__name__)


def _send_email(subject: str, body: str):
    if not all([config.ALERT_EMAIL_TO, config.ALERT_SMTP_USER, config.ALERT_SMTP_PASS]):
        return
    try:
        msg = MIMEText(body)
        msg["Subject"] = f"[TradeAgent] {subject}"
        msg["From"]    = config.ALERT_SMTP_USER
        msg["To"]      = config.ALERT_EMAIL_TO
        with smtplib.SMTP_SSL(config.ALERT_SMTP_HOST, config.ALERT_SMTP_PORT) as s:
            s.login(config.ALERT_SMTP_USER, config.ALERT_SMTP_PASS)
            s.send_message(msg)
        log.info(f"Email alert sent: {subject}")
    except Exception as e:
        log.error(f"Email alert failed: {e}")


def _send_slack(subject: str, body: str):
    if not config.ALERT_SLACK_WEBHOOK:
        return
    try:
        payload = {"text": f"*[TradeAgent] {subject}*\n{body}"}
        requests.post(config.ALERT_SLACK_WEBHOOK, json=payload, timeout=5)
        log.info(f"Slack alert sent: {subject}")
    except Exception as e:
        log.error(f"Slack alert failed: {e}")


def _send_telegram(subject: str, body: str):
    if not all([config.ALERT_TELEGRAM_TOKEN, config.ALERT_TELEGRAM_CHAT_ID]):
        return
    try:
        text = f"<b>[TradeAgent] {subject}</b>\n{body}"
        url  = f"https://api.telegram.org/bot{config.ALERT_TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": config.ALERT_TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=5)
        log.info(f"Telegram alert sent: {subject}")
    except Exception as e:
        log.error(f"Telegram alert failed: {e}")


def send(subject: str, body: str) -> None:
    """Fire alert to all configured channels. Failures are logged but never propagated."""
    channels_configured = any([
        all([config.ALERT_EMAIL_TO, config.ALERT_SMTP_USER, config.ALERT_SMTP_PASS]),
        bool(config.ALERT_SLACK_WEBHOOK),
        all([config.ALERT_TELEGRAM_TOKEN, config.ALERT_TELEGRAM_CHAT_ID]),
    ])
    if not channels_configured:
        log.warning("No alert channels configured — alert not delivered: %s", subject)
        return
    _send_email(subject, body)
    _send_slack(subject, body)
    _send_telegram(subject, body)


def signal_alert(symbol: str, signal: str, score: int, price: float, reason: str):
    subject = f"{signal.upper()} signal — {symbol} @ ${price:,.2f}"
    body    = f"Signal: {signal.upper()}\nScore: {score}\nPrice: ${price:,.2f}\nReason: {reason}"
    send(subject, body)


def order_alert(symbol: str, side: str, qty: float, price: float, order_id: str):
    subject = f"Order {side.upper()} {symbol}"
    body    = f"Side: {side.upper()}\nSymbol: {symbol}\nQty: {qty}\nPrice: ${price:,.2f}\nOrder ID: {order_id}"
    send(subject, body)


def drawdown_alert(drawdown_pct: float, equity: float):
    subject = "MAX DRAWDOWN BREACHED"
    body    = f"Drawdown: {drawdown_pct:.2f}%\nCurrent Equity: ${equity:,.2f}\nTrading halted."
    send(subject, body)
