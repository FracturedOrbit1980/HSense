"""Email the authorised classification to LUD."""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

AUTHORITY_INBOX = "Olive@lud.co.za"


def send_authorisation_email(
    *,
    author: str,
    checked_at: str,
    source: str,
    rows: list[dict],
    pdf: bytes,
    verify_url: str,
) -> None:
    """Send the authorised PDF to Olive@lud.co.za through the LUD mail server."""
    host = os.environ.get("HS_SMTP_HOST", "mail.lud.co.za")
    port = int(os.environ.get("HS_SMTP_PORT", "587"))
    user = os.environ.get("HS_SMTP_USER", "")
    password = os.environ.get("HS_SMTP_PASSWORD", "")
    sender = os.environ.get("HS_SMTP_FROM", user)
    if not user or not password or not sender:
        raise RuntimeError(
            "The authorisation email to Olive@lud.co.za was not sent. "
            "mail.lud.co.za requires a mailbox login. Set HS_SMTP_USER, "
            "HS_SMTP_PASSWORD, and HS_SMTP_FROM, then authorise again."
        )

    lines = "\n".join(
        f"- {row.get('description') or ''} — {row.get('hs_code') or ''}"
        for row in rows
    ) or "- No lines"
    message = EmailMessage()
    message["Subject"] = f"HSense authorisation — {author}"
    message["From"] = sender
    message["To"] = AUTHORITY_INBOX
    message.set_content(
        "\n".join(
            [
                f"{author} authorised this HSense classification on {checked_at}.",
                f"Source: {source or 'Not recorded'}.",
                f"Authentication: {verify_url}" if verify_url else "",
                "",
                lines,
                "",
                "The one-page PDF is attached.",
            ]
        )
    )
    message.add_attachment(
        pdf,
        maintype="application",
        subtype="pdf",
        filename="hsense.pdf",
    )

    with smtplib.SMTP(host, port, timeout=20) as smtp:
        smtp.ehlo()
        if smtp.has_extn("starttls"):
            smtp.starttls()
            smtp.ehlo()
        smtp.login(user, password)
        smtp.send_message(message)
