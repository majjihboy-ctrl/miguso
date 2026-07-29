import decimal
from django.contrib import admin
from django.utils.html import format_html
from django.core.cache import cache
from import_export.admin import ImportExportModelAdmin
from .models import League, Team, Match, Profile, Tip, TipLeg
from .utils import refresh_match_prediction

# Thresholds used by MatchAdmin.create_free_tip() to decide which market
# to pick and at what confidence a pick is worth publishing. Pulled out as
# named constants so tuning the tip-generation logic doesn't require
# hunting through the action body.
HOME_WIN_XG_MARGIN = 0.6
HOME_WIN_PROB_MIN = 0.55
HOME_WIN_ODDS = decimal.Decimal("1.75")

AWAY_WIN_XG_MARGIN = 0.5
AWAY_WIN_PROB_MIN = 0.50
AWAY_WIN_ODDS = decimal.Decimal("2.40")

OVER_2_5_TOTAL_XG_MIN = 2.8
OVER_2_5_ODDS = decimal.Decimal("1.85")
OVER_2_5_CONFIDENCE_SCALE = 30

UNDER_2_5_TOTAL_XG_MAX = 2.2
UNDER_2_5_ODDS = decimal.Decimal("1.90")
UNDER_2_5_CONFIDENCE_SCALE = 40

BTTS_YES_XG_MIN = 1.1
BTTS_YES_ODDS = decimal.Decimal("1.80")
BTTS_CONFIDENCE_SCALE = 40

DOUBLE_CHANCE_PROB_MIN = 0.50
DOUBLE_CHANCE_DRAW_PROB_MIN = 0.25
HOME_DOUBLE_CHANCE_ODDS = decimal.Decimal("1.25")
AWAY_DOUBLE_CHANCE_ODDS = decimal.Decimal("1.35")

DEFAULT_ODDS = decimal.Decimal("1.85")
MIN_PUBLISH_CONFIDENCE = 55
FEATURED_CONFIDENCE_THRESHOLD = 70


def _invalidate_tip_caches():
    """Clear all cached pages whose data depends on Tip status/content.
    tips_list caches are keyed per (tip_type, bet_type) combo since there's
    no wildcard delete in Django's low-level cache API."""
    cache.delete("home_page_data")
    cache.delete("stats_page_data")
    for tip_type in ("free", "vip"):
        for bet_type in ("all", "single", "accumulator"):
            cache.delete(f"tips_list_{tip_type}_{bet_type}")


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "is_vip", "vip_expires_at", "upgrade_requested"]
    list_filter = ["is_vip", "upgrade_requested"]
    list_editable = ["is_vip"]
    search_fields = ["user__username"]
    actions = ["grant_vip_30_days"]

    @admin.action(description="Grant VIP for 30 days")
    def grant_vip_30_days(self, request, queryset):
        from django.utils import timezone
        from datetime import timedelta
        for profile in queryset:
            profile.is_vip = True
            profile.vip_expires_at = timezone.now() + timedelta(days=30)
            profile.save()
        self.message_user(request, f"VIP granted to {queryset.count()} user(s).")


@admin.register(League)
class LeagueAdmin(admin.ModelAdmin):
    list_display = ["name", "country"]
    list_filter = ["country"]
    search_fields = ["name", "country"]
    ordering = ["name"]


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ["name", "short_name", "league", "attack_strength", "defense_strength"]
    list_filter = ["league__country", "league"]
    search_fields = ["name", "short_name", "league__name", "league__country"]
    list_editable = ["attack_strength", "defense_strength"]
    list_per_page = 50
    autocomplete_fields = ["league"]


class TipLegInline(admin.TabularInline):
    model = TipLeg
    extra = 1
    fields = ["fixture_text", "league", "kickoff", "prediction", "odds", "status", "match"]


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = [
        "__str__",
        "kickoff",
        "status",
        "home_score",
        "away_score",
        "model_xg",
        "model_probs",
    ]
    list_filter = ["status", "league", "kickoff"]
    search_fields = ["home_team__name", "away_team__name"]
    list_editable = ["status", "home_score", "away_score"]
    date_hierarchy = "kickoff"
    list_per_page = 50
    actions = ["run_poisson_model", "mark_finished", "create_free_tip"]
    autocomplete_fields = ["league", "home_team", "away_team"]

    fieldsets = (
        ("Fixture", {
            "fields": ("league", "home_team", "away_team", "kickoff", "status")
        }),
        ("Result (fill after match)", {
            "fields": ("home_score", "away_score"),
            "classes": ("collapse",),
        }),
        ("Model Predictions (auto-filled)", {
            "fields": (
                ("pred_home_goals", "pred_away_goals"),
                ("pred_home_win", "pred_draw", "pred_away_win"),
            ),
            "classes": ("collapse",),
        }),
        ("H2H / Form / Odds (optional)", {
            "fields": (
                ("h2h_home_wins", "h2h_draws", "h2h_away_wins"),
                ("home_form", "away_form"),
                ("bookmaker_odds_home", "bookmaker_odds_draw", "bookmaker_odds_away"),
            ),
            "classes": ("collapse",),
        }),
    )

    @admin.display(description="xG")
    def model_xg(self, obj):
        if obj.pred_home_goals and obj.pred_away_goals:
            return f"{obj.pred_home_goals:.1f} - {obj.pred_away_goals:.1f}"
        return "—"

    @admin.display(description="1X2 %")
    def model_probs(self, obj):
        if obj.pred_home_win:
            return format_html(
                '<span style="color:green">{}%</span> / '
                '<span style="color:#d97706">{}%</span> / '
                '<span style="color:red">{}%</span>',
                int(obj.pred_home_win * 100),
                int(obj.pred_draw * 100),
                int(obj.pred_away_win * 100),
            )
        return "—"

    @admin.action(description="Run Poisson model")
    def run_poisson_model(self, request, queryset):
        for match in queryset:
            try:
                refresh_match_prediction(match)
            except Exception as e:
                self.message_user(request, f"Error on {match}: {e}", level="ERROR")
                continue
        self.message_user(request, f"Poisson model run on {queryset.count()} matches.")

    @admin.action(description="Mark as FINISHED (enter scores first)")
    def mark_finished(self, request, queryset):
        updated = 0
        for match in queryset:
            if match.home_score is not None and match.away_score is not None:
                match.status = "finished"
                match.save()
                updated += 1
        self.message_user(request, f"Marked {updated} matches as finished.")

    @admin.action(description="Create FREE tip from match")
    def create_free_tip(self, request, queryset):
        from predictions.prediction_engine import predict_match

        created_count = 0
        for match in queryset:
            # Ensure model is run
            if not match.pred_home_goals:
                try:
                    refresh_match_prediction(match)
                except Exception:
                    continue

            h_xg = match.pred_home_goals or 0
            a_xg = match.pred_away_goals or 0
            h_prob = match.pred_home_win or 0
            d_prob = match.pred_draw or 0
            a_prob = match.pred_away_win or 0
            total_xg = h_xg + a_xg

            # Simple criteria
            prediction = None
            odds = DEFAULT_ODDS
            confidence = 50

            if h_xg - a_xg > HOME_WIN_XG_MARGIN and h_prob > HOME_WIN_PROB_MIN:
                prediction, odds, confidence = "Home Win", HOME_WIN_ODDS, int(h_prob * 100)
            elif a_xg - h_xg > AWAY_WIN_XG_MARGIN and a_prob > AWAY_WIN_PROB_MIN:
                prediction, odds, confidence = "Away Win", AWAY_WIN_ODDS, int(a_prob * 100)
            elif total_xg > OVER_2_5_TOTAL_XG_MIN:
                prediction, odds, confidence = "Over 2.5 Goals", OVER_2_5_ODDS, min(int(total_xg * OVER_2_5_CONFIDENCE_SCALE), 85)
            elif total_xg < UNDER_2_5_TOTAL_XG_MAX:
                prediction, odds, confidence = "Under 2.5 Goals", UNDER_2_5_ODDS, min(int((3.0 - total_xg) * UNDER_2_5_CONFIDENCE_SCALE), 80)
            elif h_xg > BTTS_YES_XG_MIN and a_xg > BTTS_YES_XG_MIN:
                prediction, odds, confidence = "BTTS Yes", BTTS_YES_ODDS, min(int(((h_xg + a_xg) / 3) * BTTS_CONFIDENCE_SCALE), 80)
            elif h_prob > DOUBLE_CHANCE_PROB_MIN and d_prob > DOUBLE_CHANCE_DRAW_PROB_MIN:
                prediction, odds, confidence = "1X", HOME_DOUBLE_CHANCE_ODDS, int((h_prob + d_prob) * 100)
            elif a_prob > DOUBLE_CHANCE_PROB_MIN and d_prob > DOUBLE_CHANCE_DRAW_PROB_MIN:
                prediction, odds, confidence = "X2", AWAY_DOUBLE_CHANCE_ODDS, int((a_prob + d_prob) * 100)

            if not prediction or confidence < MIN_PUBLISH_CONFIDENCE:
                continue

            # Skip if a free tip for this exact match already exists, instead
            # of get_or_create()-ing on blank/generic fields that were
            # identical for every match (which meant only the very first
            # match processed ever actually created a Tip).
            if TipLeg.objects.filter(match=match, tip__tip_type="free").exists():
                continue

            tip = Tip.objects.create(
                title="",
                tip_type="free",
                bet_type="single",
                status="pending",
                stake=decimal.Decimal("1.00"),
                description=f"Model-based pick: {prediction} (confidence: {confidence}%). xG: {h_xg:.1f} vs {a_xg:.1f}",
                is_featured=confidence >= FEATURED_CONFIDENCE_THRESHOLD,
            )
            TipLeg.objects.create(
                tip=tip,
                match=match,
                fixture_text=f"{match.home_team} vs {match.away_team}",
                league=match.league.name,
                kickoff=match.kickoff,
                prediction=prediction,
                odds=odds,
            )
            created_count += 1

        if created_count:
            _invalidate_tip_caches()
        self.message_user(request, f"Created {created_count} free tips from selected matches.")


@admin.register(Tip)
class TipAdmin(ImportExportModelAdmin):
    list_display = [
        "title",
        "tip_type",
        "bet_type",
        "status",
        "total_odds_display",
        "stake",
        "created_at",
        "is_featured",
    ]
    list_filter = ["tip_type", "bet_type", "status", "is_featured", "created_at"]
    search_fields = ["title", "description", "legs__fixture_text"]
    inlines = [TipLegInline]
    actions = ["mark_won", "mark_lost", "mark_pending", "feature_tips", "unfeature_tips"]
    date_hierarchy = "created_at"
    list_per_page = 50
    list_editable = ["status", "is_featured"]

    def total_odds_display(self, obj):
        return obj.total_odds
    total_odds_display.short_description = "Odds"

    @admin.action(description="Mark as WON")
    def mark_won(self, request, queryset):
        queryset.update(status="won")
        _invalidate_tip_caches()

    @admin.action(description="Mark as LOST")
    def mark_lost(self, request, queryset):
        queryset.update(status="lost")
        _invalidate_tip_caches()

    @admin.action(description="Mark as PENDING")
    def mark_pending(self, request, queryset):
        queryset.update(status="pending")
        _invalidate_tip_caches()

    @admin.action(description="Set FEATURED")
    def feature_tips(self, request, queryset):
        queryset.update(is_featured=True)
        _invalidate_tip_caches()

    @admin.action(description="Remove FEATURED")
    def unfeature_tips(self, request, queryset):
        queryset.update(is_featured=False)
        _invalidate_tip_caches()


@admin.register(TipLeg)
class TipLegAdmin(admin.ModelAdmin):
    list_display = ["fixture_text", "prediction", "odds", "status", "tip"]
    list_filter = ["status", "tip__tip_type"]
    search_fields = ["fixture_text", "prediction"]
    list_editable = ["status"]
    autocomplete_fields = ["tip", "match"]