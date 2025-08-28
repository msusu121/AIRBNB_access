# utils/mailer.py
import os, smtplib
from email.message import EmailMessage

def send_email_html(
    subject: str,
    to_email: str,
    html: str,
    *,
    text_fallback: str | None = None,
    attachments=None,
    inline=None,
    timeout: int = 20,
) -> None:
    server   = os.getenv("SMTP_HOST", "")
    port     = int(os.getenv("SMTP_PORT", "25"))
    user     = os.getenv("SMTP_USER", "")
    pwd      = os.getenv("SMTP_PASS", "")
    sender   = os.getenv("SMTP_FROM", user or "no-reply@example.com")
    require_auth = os.getenv("MAIL_REQUIRE_AUTH", "1") in ("1","true","True")

    if not server or not port:
        raise RuntimeError("MAIL_SERVER/MAIL_PORT required")

    # Build message
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = to_email

    if not text_fallback:
        text_fallback = "Please view this message in an HTML-capable email client."
    msg.set_content(text_fallback)
    msg.add_alternative(html, subtype="html")

    # Inline images (PNG) — if you pass {'qr@cid': b'...'}
    if inline:
        html_part = msg.get_body("html") or msg
        for cid, data in inline.items():
            html_part.add_related(
                data, maintype="image", subtype="png",
                cid=f"<{cid}>", filename=f"{cid}.png"
            )

    # Attachments: [(filename, bytes, 'mime/type'), ...]
    if attachments:
        for filename, data, mime in attachments:
            mt, st = (mime.split("/", 1) + ["octet-stream"])[:2]
            msg.add_attachment(data, maintype=mt, subtype=st, filename=filename)

    # Plain SMTP (no SSL/TLS)
    with smtplib.SMTP(server, port, timeout=timeout) as smtp:
        smtp.ehlo()
        caps = smtp.esmtp_features or {}
        auth_offered = "auth" in caps  # server advertised AUTH on plaintext

        if require_auth:
            if not auth_offered:
                raise RuntimeError("Server does not advertise AUTH on plain connection (set MAIL_REQUIRE_AUTH=0 or enable TLS/SSL).")
            smtp.login(user, pwd)

        else:
            # Try to auth if offered; otherwise send without auth
            if auth_offered and user and pwd:
                try:
                    smtp.login(user, pwd)
                except Exception:
                    # fall back to unauthenticated if server allows relay from your IP
                    pass

        smtp.send_message(msg)
