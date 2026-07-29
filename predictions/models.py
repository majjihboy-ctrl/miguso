from django.db import models
from django.contrib.auth.models import User
import decimal


class StripeEvent(models.Model):
    """Records processed Stripe webhook event IDs so retried webhook
    deliveries (which Stripe sends on any non-2xx response or timeout)
    don't re-apply side effects like re-granting VIP access."""

    event_id = models.CharField(max_length=255, unique=True)
    received_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.event_id


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    is_vip = models.BooleanField(default=False)
    vip_expires_at = models.DateTimeField(null=True, blank=True)
    phone = models.CharField(max_length=20, blank=True, default="")
    upgrade_requested = models.BooleanField(default=False)

    @property
    def is_vip_active(self):
        from django.utils import timezone
        if not self.is_vip:
            return False
        if self.vip_expires_at and self.vip_expires_at < timezone.now():
            return False
        return True

    def __str__(self):
        return f"{self.user.username} Profile"


class League(models.Model):
    name = models.CharField(max_length=100)
    country = models.CharField(max_length=100)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.country})"


class Team(models.Model):
    name = models.CharField(max_length=100)
    short_name = models.CharField(max_length=10)
    league = models.ForeignKey(League, on_delete=models.CASCADE, related_name="teams")
    crest_color = models.CharField(max_length=7, default="#1a3a5c")
    attack_strength = models.FloatField(default=1.0)
    defense_strength = models.FloatField(default=1.0)
    home_advantage = models.FloatField(default=1.15)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Match(models.Model):
    STATUS_CHOICES = [
        ("scheduled", "Scheduled"),
        ("live", "Live"),
        ("finished", "Finished"),
        ("postponed", "Postponed"),
    ]

    league = models.ForeignKey(League, on_delete=models.CASCADE, related_name="matches")
    home_team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="home_matches")
    away_team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="away_matches")
    kickoff = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="scheduled")
    home_score = models.IntegerField(null=True, blank=True)
    away_score = models.IntegerField(null=True, blank=True)

    # Model predictions
    pred_home_goals = models.FloatField(null=True, blank=True)
    pred_away_goals = models.FloatField(null=True, blank=True)
    pred_home_win = models.FloatField(null=True, blank=True)
    pred_draw = models.FloatField(null=True, blank=True)
    pred_away_win = models.FloatField(null=True, blank=True)

    # H2H / Form / Odds (fetched from API-Football)
    h2h_home_wins = models.IntegerField(null=True, blank=True)
    h2h_draws = models.IntegerField(null=True, blank=True)
    h2h_away_wins = models.IntegerField(null=True, blank=True)

    home_form = models.CharField(max_length=10, blank=True, default="")
    away_form = models.CharField(max_length=10, blank=True, default="")

    bookmaker_odds_home = models.FloatField(null=True, blank=True)
    bookmaker_odds_draw = models.FloatField(null=True, blank=True)
    bookmaker_odds_away = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ["-kickoff"]
        verbose_name_plural = "matches"

    def __str__(self):
        return f"{self.home_team} vs {self.away_team}"


class Tip(models.Model):
    TIP_TYPE = [("free", "Free"), ("vip", "VIP")]
    BET_TYPE = [("single", "Single"), ("accumulator", "Accumulator")]
    STATUS = [("pending", "Pending"), ("won", "Won"), ("lost", "Lost"), ("void", "Void")]

    title = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Optional title, e.g. 'Saturday Mega Acca'",
    )
    tip_type = models.CharField(max_length=10, choices=TIP_TYPE, default="free")
    bet_type = models.CharField(max_length=15, choices=BET_TYPE, default="single")
    status = models.CharField(max_length=10, choices=STATUS, default="pending")

    stake = models.DecimalField(
        max_digits=4, decimal_places=2, default=decimal.Decimal("1.00")
    )
    description = models.TextField(blank=True, help_text="Analysis / reasoning")
    created_at = models.DateTimeField(auto_now_add=True)
    result_entered_at = models.DateTimeField(null=True, blank=True)
    is_featured = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title or f"{self.get_tip_type_display()} {self.get_bet_type_display()} #{self.id}"

    @property
    def total_odds(self):
        legs = self.legs.all()
        if not legs:
            return None
        total = decimal.Decimal("1.00")
        for leg in legs:
            total *= leg.odds
        return total.quantize(decimal.Decimal("0.01"))

    @property
    def profit(self):
        if self.status == "won":
            return (
                self.stake * (self.total_odds - decimal.Decimal("1"))
                if self.total_odds
                else decimal.Decimal("0")
            )
        elif self.status == "lost":
            return -self.stake
        return decimal.Decimal("0")

    def evaluate(self):
        legs = self.legs.all()
        if not legs or any(l.status == "pending" for l in legs):
            return
        if any(l.status == "lost" for l in legs):
            self.status = "lost"
        elif all(l.status == "won" for l in legs):
            self.status = "won"
        else:
            self.status = "void"
        self.save()


class TipLeg(models.Model):
    STATUS = [("pending", "Pending"), ("won", "Won"), ("lost", "Lost"), ("void", "Void")]

    tip = models.ForeignKey(Tip, on_delete=models.CASCADE, related_name="legs")
    match = models.ForeignKey(
        Match,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tip_legs",
    )

    fixture_text = models.CharField(
        max_length=200, help_text="e.g. 'Man City vs Liverpool'"
    )
    league = models.CharField(max_length=100, blank=True, default="")
    kickoff = models.DateTimeField(null=True, blank=True)

    prediction = models.CharField(
        max_length=100, help_text="e.g. 'Over 2.5 Goals', '1X', 'Home Win'"
    )
    odds = models.DecimalField(max_digits=6, decimal_places=2)

    status = models.CharField(max_length=10, choices=STATUS, default="pending")
    actual_result = models.CharField(
        max_length=50, blank=True, help_text="e.g. '2-1' or 'Lost'"
    )

    model_home_goals = models.FloatField(null=True, blank=True)
    model_away_goals = models.FloatField(null=True, blank=True)
    model_home_prob = models.FloatField(null=True, blank=True)
    model_draw_prob = models.FloatField(null=True, blank=True)
    model_away_prob = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.fixture_text} — {self.prediction} @ {self.odds}"