import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils.html import escape


logger = logging.getLogger("finoraapp")


def _format_preferred_date(submission):
    if not submission.preferred_date:
        return "Not provided"
    return submission.preferred_date.strftime("%d %b %Y")


def send_booking_notification(submission) -> bool:
    recipients = getattr(settings, "BOOKING_NOTIFICATION_EMAILS", [])
    if not recipients:
        logger.info(
            "Skipping booking notification email for submission %s because BOOKING_NOTIFICATION_EMAILS is empty.",
            submission.pk,
        )
        return False

    preferred_date = _format_preferred_date(submission)
    whatsapp = submission.whatsapp or "Not provided"
    email = submission.email or "Not provided"
    message = submission.message or "No extra message provided."

    subject = f"New booking enquiry: {submission.service} - {submission.name}"
    text_body = "\n".join(
        [
            "A new booking enquiry was submitted on the Ithihasam website.",
            "",
            f"Name: {submission.name}",
            f"Phone: {submission.phone}",
            f"WhatsApp: {whatsapp}",
            f"Email: {email}",
            f"Service: {submission.service}",
            f"City/Area: {submission.city}",
            f"Preferred Date: {preferred_date}",
            f"Submitted At: {submission.created_at.strftime('%d %b %Y %I:%M %p')}",
            "",
            "Customer Message:",
            message,
        ]
    )
    html_body = f"""
        <h2>New booking enquiry</h2>
        <p>A new booking enquiry was submitted on the Ithihasam website.</p>
        <table cellpadding="6" cellspacing="0" border="0">
          <tr><td><strong>Name</strong></td><td>{escape(submission.name)}</td></tr>
          <tr><td><strong>Phone</strong></td><td>{escape(submission.phone)}</td></tr>
          <tr><td><strong>WhatsApp</strong></td><td>{escape(whatsapp)}</td></tr>
          <tr><td><strong>Email</strong></td><td>{escape(email)}</td></tr>
          <tr><td><strong>Service</strong></td><td>{escape(submission.service)}</td></tr>
          <tr><td><strong>City/Area</strong></td><td>{escape(submission.city)}</td></tr>
          <tr><td><strong>Preferred Date</strong></td><td>{escape(preferred_date)}</td></tr>
          <tr><td><strong>Submitted At</strong></td><td>{escape(submission.created_at.strftime('%d %b %Y %I:%M %p'))}</td></tr>
        </table>
        <h3>Customer Message</h3>
        <p>{escape(message).replace(chr(10), "<br />")}</p>
    """

    try:
        email_message = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=recipients,
            reply_to=[submission.email] if submission.email else None,
        )
        email_message.attach_alternative(html_body, "text/html")
        email_message.send(fail_silently=False)
        return True
    except Exception:
        logger.exception(
            "Failed to send booking notification email for submission %s.",
            submission.pk,
        )
        return False
