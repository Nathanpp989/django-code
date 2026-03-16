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

    def handle(self, *args, **kwargs):
        for name, path in self.CERTS.items():
            try:
                result = subprocess.run(
                    ["openssl", "x509", "-enddate", "-noout", "-in", path],
                    capture_output=True, text=True
                )
                expiry_str = result.stdout.strip().replace("notAfter=", "")
                expiry = datetime.datetime.strptime(
                    expiry_str, "%b %d %H:%M:%S %Y %Z"
                )
                days_left = (expiry - datetime.datetime.utcnow()).days
                if days_left < 30:
                    self.stdout.write(self.style.WARNING(
                        f"{name} cert expires in {days_left} days ({expiry_str})"
                    ))
                else:
                    self.stdout.write(self.style.SUCCESS(
                        f"{name} cert valid for {days_left} more days"
                    ))
            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f"Could not check {name} cert: {e}"
                ))
