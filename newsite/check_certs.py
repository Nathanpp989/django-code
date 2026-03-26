"""
Management command to check SSL certificate expiry dates.

Usage:
    python manage.py check_certs

Place this file at:
    django_llm/management/commands/check_certs.py

You will also need to create:
    django_llm/management/__init__.py
    django_llm/management/commands/__init__.py
"""

from django.core.management.base import BaseCommand
import subprocess
import datetime


class Command(BaseCommand):
    help = "Check SSL certificate expiry dates"

    CERTS = {
        "Server": "/etc/nginx/ssl/server.crt",
        "Client": "/etc/nginx/ssl/client.crt",
        "CA": "/etc/nginx/ssl/ca.crt",
    }

    def add_arguments(self, parser):
        parser.add_argument(
            "--warn-days",
            type=int,
            default=30,
            help="Warn if cert expires within this many days (default: 30)"
        )

    def handle(self, *args, **kwargs):
        warn_days = kwargs["warn_days"]
        any_expiring = False

        self.stdout.write("\nChecking SSL certificates...\n")

        for name, path in self.CERTS.items():
            try:
                result = subprocess.run(
                    ["openssl", "x509", "-enddate", "-noout", "-in", path],
                    capture_output=True,
                    text=True
                )

                if result.returncode != 0:
                    self.stdout.write(self.style.ERROR(
                        f"  {name}: Could not read certificate at {path}"
                    ))
                    continue

                expiry_str = result.stdout.strip().replace("notAfter=", "")
                expiry = datetime.datetime.strptime(
                    expiry_str, "%b %d %H:%M:%S %Y %Z"
                )
                days_left = (expiry - datetime.datetime.utcnow()).days

                if days_left < 0:
                    self.stdout.write(self.style.ERROR(
                        f"  {name}: EXPIRED {abs(days_left)} days ago ({expiry_str})"
                    ))
                    any_expiring = True
                elif days_left < warn_days:
                    self.stdout.write(self.style.WARNING(
                        f"  {name}: Expires in {days_left} days ({expiry_str}) - RENEW SOON"
                    ))
                    any_expiring = True
                else:
                    self.stdout.write(self.style.SUCCESS(
                        f"  {name}: Valid for {days_left} more days (expires {expiry_str})"
                    ))

            except FileNotFoundError:
                self.stdout.write(self.style.WARNING(
                    f"  {name}: Certificate not found at {path}"
                ))
            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f"  {name}: Error checking certificate: {e}"
                ))

        self.stdout.write("")

        if any_expiring:
            self.stdout.write(self.style.WARNING(
                "Some certificates need attention. Run: make certs"
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                "All certificates are valid."
            ))
