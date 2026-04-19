"""Gmail SMTP email notifications — two-section format (Engineering / General)."""

import os
import logging
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)

DASHBOARD_URL = os.getenv("DASHBOARD_URL", "http://localhost:8080")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _esc(s):
    """HTML-escape a string."""
    if not s:
        return ""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def _days_until(date_str):
    """Return integer days until close_date, or None."""
    if not date_str:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            d = datetime.strptime(str(date_str)[:10], fmt[:len(fmt.replace("%H:%M:%S",""))])
            delta = (d.date() - datetime.now(timezone.utc).date())
            return delta.days
        except ValueError:
            continue
    return None


def _format_value(opp):
    lo = opp.get("contract_value_min") or 0
    hi = opp.get("contract_value_max") or 0
    ev = opp.get("estimated_value", "")
    if ev:
        return str(ev)
    if hi:
        return f"${lo:,.0f} – ${hi:,.0f}" if lo else f"up to ${hi:,.0f}"
    return "Not specified"


def _score_color(score):
    if score >= 70:
        return "#22c55e"   # green
    if score >= 50:
        return "#f59e0b"   # amber
    return "#ef4444"       # red


def _category_color(category):
    return "#3b82f6" if category == "engineering" else "#f59e0b"


# ─────────────────────────────────────────────────────────────────────────────
# HTML card for one opportunity
# ─────────────────────────────────────────────────────────────────────────────

def _html_card(opp):
    score = opp.get("score", 0)
    category = opp.get("category", "uncategorized")
    cat_color = _category_color(category)
    score_color = _score_color(score)

    days = _days_until(opp.get("response_deadline") or opp.get("close_date"))
    days_str = f"{days}d" if days is not None else "?"
    deadline_str = opp.get("response_deadline") or opp.get("close_date") or "N/A"

    # Summary: AI summary if score >= 65 and available, else first 200 chars of description
    if score >= 65 and opp.get("ai_summary"):
        summary_text = opp["ai_summary"]
    else:
        desc = opp.get("description", "") or ""
        summary_text = desc[:200] + ("..." if len(desc) > 200 else "")

    go_nogo = opp.get("ai_go_no_go", "")
    go_color = "#22c55e" if go_nogo == "GO" else "#ef4444"
    go_badge = (f'<span style="display:inline-block;padding:2px 10px;border-radius:4px;'
                f'background:{go_color};color:#fff;font-weight:700;font-size:12px;'
                f'letter-spacing:1px;">{_esc(go_nogo)}</span>') if go_nogo else ""

    red_flags = opp.get("ai_red_flags", "")
    green_flags_raw = opp.get("ai_recommendation", "")

    flags_html = ""
    if red_flags:
        flags_html += (f'<div style="margin-top:6px;font-size:12px;color:#ef4444;">'
                       f'&#9888; Red Flags: {_esc(red_flags)}</div>')
    if green_flags_raw:
        flags_html += (f'<div style="margin-top:4px;font-size:12px;color:#22c55e;">'
                       f'&#10003; {_esc(green_flags_raw)}</div>')

    url = opp.get("url", "#")
    source = opp.get("source", "")

    return f"""
<div style="background:#1a1a2e;border-radius:8px;margin-bottom:16px;overflow:hidden;border:1px solid #2d2d4e;">
  <!-- Category header bar -->
  <div style="background:{cat_color};padding:4px 16px;font-size:11px;font-weight:700;
              color:#fff;letter-spacing:1px;text-transform:uppercase;">
    {_esc(category)} &nbsp;·&nbsp; {_esc(source)}
  </div>
  <div style="padding:14px 16px;">
    <!-- Score + Agency row -->
    <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px;">
      <div style="font-size:12px;color:#9ca3af;">
        <span style="background:{score_color};color:#fff;font-weight:700;padding:2px 8px;
                     border-radius:4px;font-size:13px;">{score}/100</span>
        &nbsp;·&nbsp; {_esc(opp.get("agency", "N/A"))}
      </div>
      {go_badge}
    </div>
    <!-- Title -->
    <div style="font-size:16px;font-weight:700;color:#e2e8f0;margin-bottom:8px;
                line-height:1.3;">
      {_esc(opp.get("title", "Untitled"))}
    </div>
    <!-- Meta line -->
    <div style="font-size:12px;color:#9ca3af;margin-bottom:8px;">
      Value: {_esc(_format_value(opp))}
      &nbsp;·&nbsp; Closes: {_esc(str(deadline_str)[:10])} ({days_str} days)
      &nbsp;·&nbsp; Set-Aside: {_esc(opp.get("set_aside") or "None")}
      &nbsp;·&nbsp; NAICS: {_esc(opp.get("naics_code") or "N/A")}
    </div>
    <!-- Summary -->
    <div style="font-size:13px;color:#cbd5e1;margin-bottom:8px;line-height:1.5;">
      {_esc(summary_text)}
    </div>
    {flags_html}
    <!-- Link -->
    <div style="margin-top:10px;">
      <a href="{_esc(url)}" style="color:#60a5fa;font-size:12px;text-decoration:none;">
        &#8594; View on SAM.gov
      </a>
    </div>
  </div>
</div>"""


# ─────────────────────────────────────────────────────────────────────────────
# Section block (Engineering or General)
# ─────────────────────────────────────────────────────────────────────────────

def _html_section(label, emoji, color, opps):
    cards = "".join(_html_card(o) for o in opps)
    return f"""
<div style="margin-bottom:32px;">
  <div style="border-bottom:2px solid {color};padding-bottom:6px;margin-bottom:16px;
              display:flex;align-items:center;gap:8px;">
    <span style="font-size:18px;">{emoji}</span>
    <span style="font-size:16px;font-weight:700;color:{color};letter-spacing:1px;
                 text-transform:uppercase;">{label}</span>
    <span style="color:#6b7280;font-size:13px;">({len(opps)})</span>
  </div>
  {cards}
</div>"""


# ─────────────────────────────────────────────────────────────────────────────
# Plaintext card + section
# ─────────────────────────────────────────────────────────────────────────────

def _text_card(opp):
    score = opp.get("score", 0)
    days = _days_until(opp.get("response_deadline") or opp.get("close_date"))
    days_str = f"{days}d" if days is not None else "?"
    deadline_str = str(opp.get("response_deadline") or opp.get("close_date") or "N/A")[:10]

    if score >= 65 and opp.get("ai_summary"):
        summary = opp["ai_summary"]
    else:
        desc = opp.get("description", "") or ""
        summary = desc[:200] + ("..." if len(desc) > 200 else "")

    go_nogo = opp.get("ai_go_no_go", "")
    lines = [
        f"  SCORE: {score}/100  ·  {opp.get('agency', 'N/A')}",
        f"  {opp.get('title', 'Untitled')}",
        f"  Value: {_format_value(opp)}  ·  Closes: {deadline_str} ({days_str} days)",
        f"  Set-Aside: {opp.get('set_aside') or 'None'}  ·  NAICS: {opp.get('naics_code') or 'N/A'}",
        f"  Source: {opp.get('source', '')}",
        "",
        f"  {summary}",
    ]
    if go_nogo:
        lines.append(f"\n  GO / NO-GO: {go_nogo}")
    if opp.get("ai_red_flags"):
        lines.append(f"  Red Flags: {opp['ai_red_flags']}")
    if opp.get("ai_recommendation"):
        lines.append(f"  Green Flags: {opp['ai_recommendation']}")
    lines.append(f"\n  → {opp.get('url', '#')}")
    lines.append("  " + "─ " * 20)
    return "\n".join(lines)


def _text_section(label, emoji, opps):
    sep = "─" * 41
    cards = "\n\n".join(_text_card(o) for o in opps)
    return f"\n{emoji}  {label.upper()}  ({len(opps)})\n{sep}\n{cards}\n"


# ─────────────────────────────────────────────────────────────────────────────
# Build full email (HTML + plaintext)
# ─────────────────────────────────────────────────────────────────────────────

def _build_subject(eng_opps, gen_opps, date_str):
    if eng_opps and gen_opps:
        return (f"[Icarus Dynamics] Contract Scan — {date_str} | "
                f"{len(eng_opps)} Engineering · {len(gen_opps)} General")
    if eng_opps:
        return (f"[Icarus Dynamics] Contract Scan — {date_str} | "
                f"{len(eng_opps)} Engineering Opportunities")
    return (f"[Icarus Dynamics] Contract Scan — {date_str} | "
            f"{len(gen_opps)} General Opportunities")


def _build_html(eng_opps, gen_opps, total_scanned, total_above, date_label):
    sections = ""
    if eng_opps:
        sections += _html_section("Engineering Opportunities", "⚙️", "#3b82f6", eng_opps)
    if gen_opps:
        sections += _html_section("General Opportunities", "🔧", "#f59e0b", gen_opps)

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0f0f1a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <div style="max-width:680px;margin:0 auto;padding:24px 16px;">

    <!-- Header -->
    <div style="border-bottom:1px solid #2d2d4e;padding-bottom:16px;margin-bottom:24px;">
      <div style="font-size:11px;font-weight:700;letter-spacing:2px;color:#6b7280;
                  text-transform:uppercase;margin-bottom:4px;">Icarus Dynamics</div>
      <div style="font-size:22px;font-weight:700;color:#e2e8f0;">Contract Scan</div>
      <div style="font-size:13px;color:#9ca3af;margin-top:4px;">{_esc(date_label)}</div>
    </div>

    <!-- Opportunity sections -->
    {sections}

    <!-- Footer -->
    <div style="border-top:1px solid #2d2d4e;padding-top:16px;margin-top:8px;
                font-size:12px;color:#6b7280;text-align:center;">
      {total_scanned} opportunities scanned &nbsp;·&nbsp; {total_above} above threshold
      &nbsp;·&nbsp;
      <a href="{_esc(DASHBOARD_URL)}" style="color:#60a5fa;text-decoration:none;">
        View dashboard →
      </a>
    </div>

  </div>
</body>
</html>"""


def _build_plaintext(eng_opps, gen_opps, total_scanned, total_above, date_label):
    divider = "━" * 41
    body = f"{divider}\nICARUS DYNAMICS — CONTRACT SCAN\n{date_label}\n{divider}\n"
    if eng_opps:
        body += _text_section("Engineering Opportunities", "⚙️", eng_opps)
    if gen_opps:
        body += _text_section("General Opportunities", "🔧", gen_opps)
    body += (f"\n{divider}\n"
             f"{total_scanned} opportunities scanned  ·  {total_above} above threshold\n"
             f"View dashboard → {DASHBOARD_URL}\n"
             f"{divider}\n")
    return body


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def _is_still_open(opp):
    """Return True if the opportunity deadline is within 1 day grace or unknown."""
    dl = opp.get("response_deadline") or ""
    if not dl:
        return True  # No deadline = BAA or rolling — treat as open
    for fmt, length in [("%Y-%m-%dT%H:%M:%S", 19), ("%Y-%m-%d", 10), ("%m/%d/%Y", 10)]:
        try:
            d = datetime.strptime(str(dl)[:length], fmt)
            return (datetime.now() - d).days <= 1  # 1 day grace
        except ValueError:
            continue
    return True


def send_high_priority_alert(opp):
    """
    Fire an immediate single-opportunity high-priority alert email.
    Called individually per opportunity (not batched) when score >= high_value_alert_threshold.
    """
    gmail_user = os.getenv("GMAIL_ADDRESS", "")
    gmail_app_password = os.getenv("GMAIL_APP_PASSWORD", "")
    to_email = os.getenv("NOTIFICATION_EMAIL", "")

    if not all([gmail_user, gmail_app_password, to_email]):
        logger.warning("Gmail SMTP not fully configured, skipping high-priority alert")
        return False

    score = opp.get("score", 0)
    title = opp.get("title", "Untitled")
    subject = f"\U0001f6a8 [Icarus Dynamics] HIGH PRIORITY: {title[:60]} \u2014 Score {score}/100"

    card_html = _html_card(opp)
    now = datetime.now()
    date_label = now.strftime("%A, %B %d, %Y").replace(" 0", " ")

    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0f0f1a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <div style="max-width:680px;margin:0 auto;padding:24px 16px;">
    <div style="border-bottom:1px solid #ef4444;padding-bottom:16px;margin-bottom:24px;">
      <div style="font-size:11px;font-weight:700;letter-spacing:2px;color:#ef4444;
                  text-transform:uppercase;margin-bottom:4px;">\U0001f6a8 Icarus Dynamics \u2014 High Priority Alert</div>
      <div style="font-size:22px;font-weight:700;color:#e2e8f0;">Score {score}/100 \u2014 Act Now</div>
      <div style="font-size:13px;color:#9ca3af;margin-top:4px;">{_esc(date_label)}</div>
    </div>
    {card_html}
    <div style="border-top:1px solid #2d2d4e;padding-top:16px;margin-top:8px;
                font-size:12px;color:#6b7280;text-align:center;">
      <a href="{_esc(DASHBOARD_URL)}" style="color:#60a5fa;text-decoration:none;">
        View dashboard \u2192
      </a>
    </div>
  </div>
</body>
</html>"""

    score_color = _score_color(score)
    text_body = (
        f"*** HIGH PRIORITY ALERT — Score {score}/100 ***\n"
        f"{title}\n"
        f"Agency: {opp.get('agency', 'N/A')}\n"
        f"Value: {_format_value(opp)}\n"
        f"Deadline: {opp.get('response_deadline', 'N/A')}\n"
        f"Set-Aside: {opp.get('set_aside') or 'None'}\n"
        f"NAICS: {opp.get('naics_code', 'N/A')}\n\n"
        f"AI Summary: {opp.get('ai_summary', opp.get('description', '')[:300])}\n\n"
        f"GO/NO-GO: {opp.get('ai_go_no_go', 'Not assessed')}\n"
        f"Recommendation: {opp.get('ai_recommendation', '')}\n\n"
        f"-> {opp.get('url', '#')}\n"
        f"\nView dashboard -> {DASHBOARD_URL}\n"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(gmail_user, gmail_app_password)
            server.sendmail(gmail_user, to_email, msg.as_string())
        logger.info(f"High-priority alert sent: '{title[:60]}' (score {score})")
        return True
    except Exception as e:
        logger.error(f"Failed to send high-priority alert: {e}")
        return False


def send_notification(opportunities, score_threshold=50):
    """
    Send two-section email digest of NEW (unnotified) opportunities only.
    Marks included opportunities as notified=True in-place on success.
    Falls back to single-section if naics_categories is missing from config.
    """
    gmail_user = os.getenv("GMAIL_ADDRESS", "")
    gmail_app_password = os.getenv("GMAIL_APP_PASSWORD", "")
    to_email = os.getenv("NOTIFICATION_EMAIL", "")

    if not all([gmail_user, gmail_app_password, to_email]):
        logger.warning("Gmail SMTP not fully configured, skipping email")
        return False

    qualifying = [
        o for o in opportunities
        if o.get("score", 0) >= score_threshold
        and not o.get("notified", False)
        and o.get("status") != "SKIP"
        and _is_still_open(o)
    ]
    if not qualifying:
        logger.info("No new unnotified opportunities above threshold — no email sent")
        return False

    qualifying.sort(key=lambda x: x.get("score", 0), reverse=True)

    eng_opps = [o for o in qualifying if o.get("category") == "engineering"]
    gen_opps = [o for o in qualifying if o.get("category") == "general"]

    # If categories are not populated at all, fall back to legacy single section
    has_categories = any(o.get("category") for o in qualifying)
    if not has_categories:
        eng_opps = qualifying
        gen_opps = []

    if not eng_opps and not gen_opps:
        logger.info("No qualifying categorized opportunities — no email sent")
        return False

    total_scanned = len(opportunities)
    total_above = sum(1 for o in opportunities if o.get("score", 0) >= score_threshold)
    now = datetime.now()
    date_label = now.strftime("%A, %B %-d, %Y") if os.name != "nt" else now.strftime("%A, %B %d, %Y").replace(" 0", " ")
    date_str = now.strftime("%Y-%m-%d")

    subject = _build_subject(eng_opps, gen_opps, date_str)
    html_body = _build_html(eng_opps, gen_opps, total_scanned, total_above, date_label)
    text_body = _build_plaintext(eng_opps, gen_opps, total_scanned, total_above, date_label)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(gmail_user, gmail_app_password)
            server.sendmail(gmail_user, to_email, msg.as_string())
        # Mark all included opportunities as notified
        for opp in qualifying:
            opp["notified"] = True
        logger.info(f"Email sent to {to_email} — {len(eng_opps)} eng + {len(gen_opps)} gen")
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Weekly pipeline digest
# ─────────────────────────────────────────────────────────────────────────────

_TERMINAL_STATUSES = {"no-bid", "applied", "won", "lost"}


def send_weekly_digest(opportunities, score_threshold=50):
    """
    Send a compact pipeline digest of all active high-scoring opportunities
    that have already been notified but are not yet resolved.
    """
    gmail_user = os.getenv("GMAIL_ADDRESS", "")
    gmail_app_password = os.getenv("GMAIL_APP_PASSWORD", "")
    to_email = os.getenv("NOTIFICATION_EMAIL", "")

    if not all([gmail_user, gmail_app_password, to_email]):
        logger.warning("Gmail SMTP not fully configured, skipping weekly digest")
        return False

    active = [
        o for o in opportunities
        if o.get("notified", False)
        and o.get("score", 0) >= score_threshold
        and o.get("status") not in _TERMINAL_STATUSES
        and o.get("status") != "SKIP"
    ]
    if not active:
        logger.info("Weekly digest: no active pipeline items — skipping")
        return False

    active.sort(key=lambda x: x.get("score", 0), reverse=True)

    now = datetime.now()
    date_label = now.strftime("%A, %B %-d, %Y") if os.name != "nt" else now.strftime("%A, %B %d, %Y").replace(" 0", " ")
    date_str = now.strftime("%Y-%m-%d")

    # Build compact HTML rows
    rows_html = ""
    rows_text = ""
    for opp in active:
        score = opp.get("score", 0)
        days = _days_until(opp.get("response_deadline") or opp.get("close_date"))
        days_str = f"{days}d" if days is not None else "?"
        status = opp.get("status", "")
        url = opp.get("url", "#")
        agency = _esc(opp.get("agency", "N/A"))
        title = _esc(opp.get("title", "Untitled"))
        score_color = _score_color(score)

        rows_html += f"""
<tr style="border-bottom:1px solid #2d2d4e;">
  <td style="padding:10px 8px;font-size:13px;color:#e2e8f0;line-height:1.3;">
    <a href="{_esc(url)}" style="color:#60a5fa;text-decoration:none;">{title}</a>
    <div style="font-size:11px;color:#9ca3af;margin-top:2px;">{agency}</div>
  </td>
  <td style="padding:10px 8px;text-align:center;white-space:nowrap;">
    <span style="background:{score_color};color:#fff;font-weight:700;padding:2px 7px;
                 border-radius:4px;font-size:12px;">{score}</span>
  </td>
  <td style="padding:10px 8px;text-align:center;font-size:12px;color:#9ca3af;white-space:nowrap;">
    {days_str}
  </td>
  <td style="padding:10px 8px;text-align:center;font-size:12px;color:#9ca3af;white-space:nowrap;">
    {_esc(status)}
  </td>
</tr>"""

        rows_text += (f"  [{score:>3}/100]  {opp.get('title', 'Untitled')[:60]}\n"
                      f"           {opp.get('agency', 'N/A')} · Closes: {days_str} · {status}\n"
                      f"           → {url}\n\n")

    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0f0f1a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
  <div style="max-width:680px;margin:0 auto;padding:24px 16px;">
    <div style="border-bottom:1px solid #2d2d4e;padding-bottom:16px;margin-bottom:24px;">
      <div style="font-size:11px;font-weight:700;letter-spacing:2px;color:#6b7280;
                  text-transform:uppercase;margin-bottom:4px;">Icarus Dynamics</div>
      <div style="font-size:22px;font-weight:700;color:#e2e8f0;">Weekly Pipeline Digest</div>
      <div style="font-size:13px;color:#9ca3af;margin-top:4px;">{_esc(date_label)} &nbsp;·&nbsp; {len(active)} active opportunities</div>
    </div>
    <table style="width:100%;border-collapse:collapse;">
      <thead>
        <tr style="border-bottom:2px solid #3b82f6;">
          <th style="padding:8px;text-align:left;font-size:11px;color:#6b7280;
                     text-transform:uppercase;letter-spacing:1px;">Opportunity</th>
          <th style="padding:8px;text-align:center;font-size:11px;color:#6b7280;
                     text-transform:uppercase;letter-spacing:1px;">Score</th>
          <th style="padding:8px;text-align:center;font-size:11px;color:#6b7280;
                     text-transform:uppercase;letter-spacing:1px;">Closes</th>
          <th style="padding:8px;text-align:center;font-size:11px;color:#6b7280;
                     text-transform:uppercase;letter-spacing:1px;">Status</th>
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>
    <div style="border-top:1px solid #2d2d4e;padding-top:16px;margin-top:24px;
                font-size:12px;color:#6b7280;text-align:center;">
      <a href="{_esc(DASHBOARD_URL)}" style="color:#60a5fa;text-decoration:none;">
        View dashboard →
      </a>
    </div>
  </div>
</body>
</html>"""

    divider = "━" * 41
    text_body = (f"{divider}\nICARUS DYNAMICS — WEEKLY PIPELINE DIGEST\n"
                 f"{date_label}  ·  {len(active)} active opportunities\n{divider}\n\n"
                 f"{rows_text}"
                 f"{divider}\nView dashboard → {DASHBOARD_URL}\n{divider}\n")

    subject = f"[Icarus Dynamics] Weekly Digest — {date_str} | {len(active)} Active"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(gmail_user, gmail_app_password)
            server.sendmail(gmail_user, to_email, msg.as_string())
        logger.info(f"Weekly digest sent to {to_email} — {len(active)} active opportunities")
        return True
    except Exception as e:
        logger.error(f"Failed to send weekly digest: {e}")
        return False
