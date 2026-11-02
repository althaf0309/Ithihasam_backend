"""Sends a test booking notification, so mail setup can be verified directly.

    python manage.py test_email
    python manage.py test_email --to someone@example.com

Reports the exact SMTP failure rather than the silent False that
send_booking_notification returns, which is what made the original
misconfiguration so hard to find.
"""

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Sends a test email using the configured SMTP settings."

    def add_arguments(self, parser):
        parser.add_argument(
            "--to",
            action="append",
            dest="recipients",
            help="Recipient address. Repeatable. Defaults to BOOKING_NOTIFICATION_EMAILS.",
        )

    def handle(self, *args, **options):
        recipients = options.get("recipients") or list(
            getattr(settings, "BOOKING_NOTIFICATION_EMAILS", [])
        )

        if not recipients:
            raise CommandError(
                "No recipients. Set BOOKING_NOTIFICATION_EMAILS in .env, or pass --to."
            )

        # Printed before sending: a wrong host or blank user is usually the
        # whole problem, and seeing it stated is faster than reading a traceback.
        self.stdout.write("Configuration in use:")
        for label, value in (
            ("EMAIL_BACKEND", settings.EMAIL_BACKEND),
            ("EMAIL_HOST", settings.EMAIL_HOST),
            ("EMAIL_PORT", settings.EMAIL_PORT),
            ("EMAIL_USE_TLS", settings.EMAIL_USE_TLS),
            ("EMAIL_HOST_USER", settings.EMAIL_HOST_USER or "(empty)"),
            ("EMAIL_HOST_PASSWORD", "(set)" if settings.EMAIL_HOST_PASSWORD else "(EMPTY - this is why mail fails)"),
            ("DEFAULT_FROM_EMAIL", settings.DEFAULT_FROM_EMAIL),
        ):
            self.stdout.write(f"  {label:<22} {value}")

        # Port and TLS flag must agree, or the server closes the connection
        # before authentication and the error gives no hint as to why.
        if settings.EMAIL_PORT == 465 and not settings.EMAIL_USE_SSL:
            self.stdout.write(
                self.style.ERROR(
                    "\n  Port 465 requires EMAIL_USE_SSL=true. Without it the connection "
                    "is closed before authentication."
                )
            )
        if settings.EMAIL_PORT == 587 and not settings.EMAIL_USE_TLS:
            self.stdout.write(
                self.style.ERROR("\n  Port 587 requires EMAIL_USE_TLS=true.")
            )

        self.stdout.write(f"\nSending to: {', '.join(recipients)}")

        message = EmailMultiAlternatives(
            subject="Ithihasam — test booking notification",
            body=(
                "This is a test from the Ithihasam website.\n\n"
                "If you are reading this, booking notification emails are working.\n\n"
                "Name: Test Customer\n"
                "Phone: +91 94000 96518\n"
                "Service: Electrical & Plumbing\n"
                "City: Thalassery\n"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=recipients,
            connection=get_connection(fail_silently=False),
        )
        message.attach_alternative(
            "<h2>Ithihasam — test booking notification</h2>"
            "<p>If you are reading this, booking notification emails are working.</p>"
            "<table cellpadding='6'>"
            "<tr><td><strong>Name</strong></td><td>Test Customer</td></tr>"
            "<tr><td><strong>Phone</strong></td><td>+91 94000 96518</td></tr>"
            "<tr><td><strong>Service</strong></td><td>Electrical &amp; Plumbing</td></tr>"
            "<tr><td><strong>City</strong></td><td>Thalassery</td></tr>"
            "</table>",
            "text/html",
        )

        try:
            sent = message.send(fail_silently=False)
        except Exception as error:
            # Surface the real reason. The common ones:
            #   535 ... Username and Password not accepted -> wrong app password
            #   SMTPAuthenticationError                    -> 2FA off, or normal
            #                                                 password used
            #   Connection refused / timed out             -> port blocked
            raise CommandError(f"{type(error).__name__}: {error}") from error

        if not sent:
            raise CommandError("The backend reported 0 messages sent.")

        self.stdout.write(self.style.SUCCESS(f"\nSent {sent} message(s). Check the inbox and spam folder."))
