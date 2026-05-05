from fastapi_mail import FastMail, MessageSchema, ConnectionConfig, MessageType
from app.config import get_settings

settings = get_settings()

_mail_config = ConnectionConfig(
    MAIL_USERNAME=settings.mail_username,
    MAIL_PASSWORD=settings.mail_password,
    MAIL_FROM=settings.mail_from,
    MAIL_PORT=settings.mail_port,
    MAIL_SERVER=settings.mail_server,
    MAIL_STARTTLS=settings.mail_starttls,
    MAIL_SSL_TLS=settings.mail_ssl_tls,
    USE_CREDENTIALS=bool(settings.mail_username),
    VALIDATE_CERTS=True,
)

_fastmail = FastMail(_mail_config)


async def send_invite_email(to_email: str, invite_link: str, inviter_name: str) -> None:
    message = MessageSchema(
        subject="You've been invited to Fliki Clone",
        recipients=[to_email],
        body=f"""
        <h2>You've been invited by {inviter_name}</h2>
        <p>Click the link below to join the workspace:</p>
        <a href="{invite_link}">{invite_link}</a>
        """,
        subtype=MessageType.html,
    )
    await _fastmail.send_message(message)


async def send_welcome_email(to_email: str, name: str) -> None:
    message = MessageSchema(
        subject="Welcome to Fliki Clone!",
        recipients=[to_email],
        body=f"""
        <h2>Welcome, {name}!</h2>
        <p>Your account has been created. Start creating amazing videos today.</p>
        """,
        subtype=MessageType.html,
    )
    await _fastmail.send_message(message)
