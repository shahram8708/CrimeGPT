from flask import current_app, url_for
from markupsafe import Markup

from app.services.email_layout import paragraphs_html, render_email
from app.services.mail_service import enqueue_email, send_email_message


def _abs(endpoint, **values):
    return url_for(endpoint, _external=True, **values)


def send_verify_email(user, raw):
    link = _abs("auth.verify_email", token=raw)
    return enqueue_email(
        to=user.email or user.identifier,
        subject="Verify your CrimeGPT account",
        body=(
            f"Namaste {user.full_name},\n\n"
            f"Confirm this email for CrimeGPT:\n{link}\n\n"
            "This link expires in 24 hours. If you did not register, ignore this message.\n"
        ),
        html=render_email(
            "email/verify.html",
            subject="Verify your CrimeGPT account",
            full_name=user.full_name,
            cta_url=link,
            cta_label="Verify email address",
            note_html=Markup("This confirmation link expires in 24 hours and can be used once."),
        ),
        purpose="verify",
        user_id=user.id,
    )


def send_reset_email(user, raw):
    link = _abs("auth.reset_password", token=raw)
    return enqueue_email(
        to=user.email or user.identifier,
        subject="Reset your CrimeGPT password",
        body=(
            f"Namaste {user.full_name},\n\n"
            f"Reset your password using this link:\n{link}\n\n"
            "This link expires in 1 hour and can be used once.\n"
        ),
        html=render_email(
            "email/reset.html",
            subject="Reset your CrimeGPT password",
            full_name=user.full_name,
            cta_url=link,
            cta_label="Reset password",
            note_html=Markup("This reset link expires in 1 hour and can be used only once."),
        ),
        purpose="reset",
        user_id=user.id,
    )


def send_invite_email(user, raw, inviter):
    link = _abs("auth.accept_invite", token=raw)
    return enqueue_email(
        to=user.email or user.identifier,
        subject="You are invited to CrimeGPT",
        body=(
            f"Namaste {user.full_name},\n\n"
            f"{inviter.full_name} invited you to CrimeGPT as {user.role_label}.\n"
            f"Accept the invite:\n{link}\n\n"
            "This link expires in 7 days.\n"
        ),
        html=render_email(
            "email/invite.html",
            subject="You are invited to CrimeGPT",
            full_name=user.full_name,
            inviter_name=inviter.full_name,
            role_label=user.role_label,
            cta_url=link,
            cta_label="Accept invitation",
            note_html=Markup("This invitation expires in 7 days. Contact your SHO if you need a new link."),
        ),
        purpose="invite",
        user_id=user.id,
    )


def send_contact_email(row):
    subject = f"CrimeGPT contact from {row.name}"
    body = (
        f"Name: {row.name}\nEmail: {row.email}\n"
        f"Organisation: {row.organisation or '-'}\n"
        f"Station: {row.station_note or '-'}\n\n{row.message}\n"
    )
    inbox = current_app.config.get("MAIL_DEFAULT_SENDER")
    return send_email_message(
        inbox,
        subject,
        body,
        html=render_email(
            "email/contact.html",
            subject=subject,
            sender_name=row.name,
            sender_email=row.email,
            organisation=row.organisation or "-",
            station_note=row.station_note or "-",
            message_html=paragraphs_html(row.message),
        ),
        purpose="contact",
    )
