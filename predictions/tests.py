"""
Basic regression tests for the predictions app.

Run with: python manage.py test predictions
(or `pytest` if pytest-django is configured)

These deliberately cover the areas that had real bugs during review:
- Tip.profit / Tip.total_odds correctness
- The Dixon-Coles prediction engine's probability outputs
- Stripe webhook idempotency
- The stats() view no longer crashing on profit aggregation
"""
import decimal
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from .models import League, Team, Match, Tip, TipLeg, Profile, StripeEvent
from .prediction_engine import predict_match, update_team_strengths, score_prediction


class TipModelTests(TestCase):
    def setUp(self):
        self.tip = Tip.objects.create(
            tip_type="free", bet_type="single", status="pending",
            stake=decimal.Decimal("2.00"),
        )
        TipLeg.objects.create(
            tip=self.tip, fixture_text="A vs B", prediction="Over 2.5",
            odds=decimal.Decimal("1.80"),
        )

    def test_total_odds_single_leg(self):
        self.assertEqual(self.tip.total_odds, decimal.Decimal("1.80"))

    def test_total_odds_multiple_legs_multiplies(self):
        TipLeg.objects.create(
            tip=self.tip, fixture_text="C vs D", prediction="BTTS",
            odds=decimal.Decimal("1.50"),
        )
        # 1.80 * 1.50 = 2.70
        self.assertEqual(self.tip.total_odds, decimal.Decimal("2.70"))

    def test_profit_when_won(self):
        self.tip.status = "won"
        self.tip.save()
        # stake(2.00) * (odds(1.80) - 1) = 1.60
        self.assertEqual(self.tip.profit, decimal.Decimal("1.60"))

    def test_profit_when_lost(self):
        self.tip.status = "lost"
        self.tip.save()
        self.assertEqual(self.tip.profit, -decimal.Decimal("2.00"))

    def test_profit_when_pending_is_zero(self):
        self.assertEqual(self.tip.profit, decimal.Decimal("0"))

    def test_evaluate_all_legs_won_marks_tip_won(self):
        self.tip.legs.update(status="won")
        self.tip.evaluate()
        self.tip.refresh_from_db()
        self.assertEqual(self.tip.status, "won")

    def test_evaluate_any_leg_lost_marks_tip_lost(self):
        TipLeg.objects.create(
            tip=self.tip, fixture_text="C vs D", prediction="BTTS",
            odds=decimal.Decimal("1.50"), status="lost",
        )
        self.tip.legs.filter(prediction="Over 2.5").update(status="won")
        self.tip.evaluate()
        self.tip.refresh_from_db()
        self.assertEqual(self.tip.status, "lost")

    def test_evaluate_skips_while_any_leg_pending(self):
        self.tip.evaluate()
        self.tip.refresh_from_db()
        self.assertEqual(self.tip.status, "pending")


class PredictionEngineTests(TestCase):
    def test_predict_match_probabilities_sum_to_one(self):
        result = predict_match(
            home_attack=1.2, home_defense=0.9,
            away_attack=1.0, away_defense=1.1,
        )
        total = (
            result["home_win_prob"] + result["draw_prob"] + result["away_win_prob"]
        )
        self.assertAlmostEqual(total, 1.0, places=6)

    def test_predict_match_stronger_home_team_favoured(self):
        result = predict_match(
            home_attack=2.0, home_defense=0.5,
            away_attack=0.5, away_defense=2.0,
        )
        self.assertGreater(result["home_win_prob"], result["away_win_prob"])

    def test_update_team_strengths_clamped_to_bounds(self):
        home_team = {"attack_strength": 0.3, "defense_strength": 0.3, "home_advantage": 1.15}
        away_team = {"attack_strength": 3.0, "defense_strength": 3.0}
        # A blowout result that would otherwise push values far outside bounds
        updated = update_team_strengths(home_team, away_team, home_score=10, away_score=0)
        for key, value in updated.items():
            self.assertGreaterEqual(value, 0.3)
            self.assertLessEqual(value, 3.0)

    def test_update_team_strengths_uses_consistent_clamped_inputs(self):
        # Regression test: implied_home_defense previously used the raw
        # (unclamped) away_attack instead of the safe_ clamped version.
        home_team = {"attack_strength": 1.0, "defense_strength": 1.0, "home_advantage": 1.15}
        away_team = {"attack_strength": 0.0, "defense_strength": 1.0}  # would divide by zero if unclamped
        try:
            update_team_strengths(home_team, away_team, home_score=1, away_score=1)
        except ZeroDivisionError:
            self.fail("update_team_strengths raised ZeroDivisionError on zero away_attack")

    def test_score_prediction_exact_score(self):
        self.assertEqual(score_prediction(2, 1, 2, 1), 5)

    def test_score_prediction_correct_goal_difference(self):
        self.assertEqual(score_prediction(2, 1, 3, 2), 3)

    def test_score_prediction_correct_outcome_only(self):
        self.assertEqual(score_prediction(2, 0, 1, 0), 1)

    def test_score_prediction_wrong_outcome(self):
        self.assertEqual(score_prediction(2, 0, 0, 1), 0)


class StripeWebhookTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="bettor", email="bettor@example.com", password="pw12345!"
        )
        Profile.objects.get_or_create(user=self.user)

    def _fake_event(self, event_id="evt_test_1"):
        return {
            "id": event_id,
            "type": "checkout.session.completed",
            "data": {"object": {"customer_email": "bettor@example.com"}},
        }

    @patch("predictions.views.stripe.Webhook.construct_event")
    def test_webhook_grants_vip_on_first_delivery(self, mock_construct):
        mock_construct.return_value = self._fake_event()
        response = self.client.post(
            reverse("stripe_webhook"), data=b"{}", content_type="application/json",
            HTTP_STRIPE_SIGNATURE="sig",
        )
        self.assertEqual(response.status_code, 200)
        self.user.profile.refresh_from_db()
        self.assertTrue(self.user.profile.is_vip)
        self.assertEqual(StripeEvent.objects.count(), 1)

    @patch("predictions.views.stripe.Webhook.construct_event")
    def test_webhook_is_idempotent_on_retry(self, mock_construct):
        mock_construct.return_value = self._fake_event()
        for _ in range(2):
            response = self.client.post(
                reverse("stripe_webhook"), data=b"{}", content_type="application/json",
                HTTP_STRIPE_SIGNATURE="sig",
            )
            self.assertEqual(response.status_code, 200)

        # Only one StripeEvent record should exist despite two deliveries
        self.assertEqual(StripeEvent.objects.filter(event_id="evt_test_1").count(), 1)

    @patch("predictions.views.stripe.Webhook.construct_event")
    def test_webhook_handles_unexpected_error_gracefully(self, mock_construct):
        mock_construct.side_effect = RuntimeError("boom")
        response = self.client.post(
            reverse("stripe_webhook"), data=b"{}", content_type="application/json",
            HTTP_STRIPE_SIGNATURE="sig",
        )
        self.assertEqual(response.status_code, 400)


class StatsViewTests(TestCase):
    def test_stats_view_does_not_crash_and_computes_averages(self):
        tip = Tip.objects.create(
            tip_type="free", bet_type="single", status="won",
            stake=decimal.Decimal("1.00"),
        )
        TipLeg.objects.create(
            tip=tip, fixture_text="A vs B", prediction="Home Win",
            odds=decimal.Decimal("2.00"), status="won",
        )
        response = self.client.get(reverse("stats"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("avg_odds", response.context)
        self.assertIn("avg_stake", response.context)
        self.assertIn("monthly_stats", response.context)


class SitemapTests(TestCase):
    def test_sitemap_renders_without_error(self):
        Tip.objects.create(tip_type="free", bet_type="single", status="pending")
        response = self.client.get("/sitemap.xml")
        self.assertEqual(response.status_code, 200)


class RateLimitTests(TestCase):
    def test_betting_calculator_rate_limited_after_threshold(self):
        url = reverse("calculator")
        last_status = None
        for _ in range(25):
            last_status = self.client.post(
                url, data='{"stake": 10, "odds": 1.5}', content_type="application/json"
            ).status_code
        # The 21st+ request within the window should be blocked (429)
        self.assertIn(last_status, (429, 403))