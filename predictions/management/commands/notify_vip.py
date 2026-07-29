import html
import os
import requests
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from predictions.models import Tip


class Command(BaseCommand):
    help = "Send new VIP tips to Telegram channel"

    def handle(self, *args, **kwargs):
        BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
        CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

        if not BOT_TOKEN or not CHAT_ID:
            self.stdout.write(self.style.WARNING("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set"))
            return

        # Tips created in last hour that haven't been notified
        one_hour_ago = timezone.now() - timedelta(hours=1)
        tips = Tip.objects.filter(tip_type="vip", status="pending", created_at__gte=one_hour_ago)

        for tip in tips:
            lines = [f"💎 <b>VIP TIP</b>"]
            if tip.title:
                lines.append(f"<b>{html.escape(tip.title)}</b>")

            for leg in tip.legs.all():
                lines.append(
                    f"• {html.escape(leg.fixture_text)} — "
                    f"{html.escape(leg.prediction)} @ {leg.odds}"
                )

            if tip.total_odds:
                lines.append(f"\n📊 Total Odds: <b>{tip.total_odds}</b>")
                lines.append(f"💰 Suggested Stake: {tip.stake} unit(s)")

            if tip.description:
                lines.append(f"\n📝 {html.escape(tip.description[:200])}")

            text = "\n".join(lines)

            resp = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
                timeout=10,
            )

            if resp.status_code == 200:
                self.stdout.write(self.style.SUCCESS(f"Sent: {tip}"))
            else:
                self.stdout.write(self.style.ERROR(f"Failed to send tip {tip.id}: {resp.text}"))