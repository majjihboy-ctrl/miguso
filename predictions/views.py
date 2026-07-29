import decimal
import json
import stripe
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login
from django.contrib import messages
from django.db.models.functions import TruncMonth
from collections import defaultdict
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.conf import settings
from django.core.cache import cache
from datetime import timedelta
from django_ratelimit.decorators import ratelimit

from .models import Tip, Profile, Match, StripeEvent
from .forms import CustomUserCreationForm

import logging

logger = logging.getLogger(__name__)


from django.contrib.auth.views import LoginView
from django.utils.decorators import method_decorator


@method_decorator(ratelimit(key="ip", rate="10/m", block=True), name="post")
class RateLimitedLoginView(LoginView):
    """Same as Django's default LoginView, but rate-limited per IP to
    reduce brute-force login attempts."""
    template_name = "predictions/login.html"


def _vip_status(request):
    if not request.user.is_authenticated:
        return False
    try:
        return request.user.profile.is_vip_active
    except Profile.DoesNotExist:
        Profile.objects.create(user=request.user)
        return False


def home(request):
    cache_key = "home_page_data"
    data = cache.get(cache_key)
    if not data:
        featured_free = list(
            Tip.objects.filter(tip_type="free", is_featured=True, status="pending").prefetch_related("legs").order_by("-created_at")[:5])
        if not featured_free:
            featured_free = list(Tip.objects.filter(tip_type="free", status="pending").prefetch_related("legs").order_by("-created_at")[:5])

        recent_results = list(
            Tip.objects.filter(status__in=("won", "lost")).prefetch_related("legs").order_by("-result_entered_at", "-created_at")[:8])
        vip_teaser = list(Tip.objects.filter(tip_type="vip", status="pending").prefetch_related("legs").order_by("-created_at")[:3])

        finished = Tip.objects.filter(status__in=("won", "lost"))
        total_tips = finished.count()
        won_tips = finished.filter(status="won").count()
        win_rate = round(won_tips / total_tips * 100, 1) if total_tips else 0

        total_profit = sum(t.profit for t in finished)
        total_staked = sum(t.stake for t in finished)
        roi = round(total_profit / total_staked * 100, 1) if total_staked else 0

        data = {
            "featured_free": featured_free,
            "recent_results": recent_results,
            "vip_teaser": vip_teaser,
            "win_rate": win_rate,
            "total_profit": total_profit,
            "total_tips": total_tips,
            "roi": roi,
        }
        cache.set(cache_key, data, 300)

    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    data["todays_matches"] = Match.objects.filter(
        kickoff__gte=today_start,
        kickoff__lt=today_end,
        status="scheduled",  # ← FIXED
    ).select_related("league", "home_team", "away_team").order_by("kickoff")[:20]

    data["live_matches"] = Match.objects.filter(
        status="live",
    ).select_related("home_team", "away_team").order_by("-kickoff")[:10]

    data["is_vip"] = _vip_status(request)
    return render(request, "predictions/home.html", data)


def tips_list(request, tip_type):
    if tip_type not in ("free", "vip"):
        return redirect("home")

    if tip_type == "vip" and not _vip_status(request):
        messages.info(request, "VIP access is required to view these tips.")
        return redirect("upgrade")

    bet_type = request.GET.get("bet_type", "all")
    cache_key = f"tips_list_{tip_type}_{bet_type}"
    tips = cache.get(cache_key)
    if tips is None:
        tips = Tip.objects.filter(tip_type=tip_type, status="pending").prefetch_related("legs")
        if bet_type in ("single", "accumulator"):
            tips = tips.filter(bet_type=bet_type)
        tips = list(tips.order_by("-created_at"))
        cache.set(cache_key, tips, 120)

    return render(request, "predictions/tips_list.html", {
        "tips": tips,
        "tip_type": tip_type,
        "bet_type": bet_type,
        "is_vip": _vip_status(request),
    })


def tip_detail(request, pk):
    tip = get_object_or_404(Tip.objects.prefetch_related("legs"), pk=pk)
    is_vip = _vip_status(request)

    if tip.tip_type == "vip" and not is_vip:
        messages.error(request, "This is a VIP tip. Upgrade to unlock.")
        return redirect("upgrade")

    potential_return = decimal.Decimal("0")
    if tip.total_odds:
        potential_return = tip.stake * tip.total_odds

    return render(request, "predictions/tip_detail.html", {
        "tip": tip,
        "is_vip": is_vip,
        "potential_return": potential_return,
    })


def history(request):
    tips = Tip.objects.filter(status__in=("won", "lost", "void")).prefetch_related("legs").order_by("-created_at")
    return render(request, "predictions/history.html", {"tips": tips})


def stats(request):
    cache_key = "stats_page_data"
    context = cache.get(cache_key)
    if context is None:
        finished = Tip.objects.filter(status__in=("won", "lost")).prefetch_related("legs")
        total = finished.count()
        won = finished.filter(status="won").count()
        lost = total - won
        win_rate = round(won / total * 100, 1) if total else 0

        total_profit = sum(t.profit for t in finished)
        total_staked = sum(t.stake for t in finished)
        roi = round(total_profit / total_staked * 100, 1) if total_staked else 0

        avg_odds = decimal.Decimal("0")
        odds_count = 0
        for t in finished:
            if t.total_odds:
                avg_odds += t.total_odds
                odds_count += 1
        avg_odds = avg_odds / odds_count if odds_count else decimal.Decimal("0")
        avg_stake = total_staked / total if total else decimal.Decimal("0")

        recent_form = list(finished.order_by("-created_at")[:10])

        # `profit` is a Python @property on Tip, not a DB column, so it can't be
        # summed in the database. Group tips by real calendar month (TruncMonth)
        # and sum their `.profit` values in Python instead.
        six_months_ago = timezone.now() - timedelta(days=180)
        recent_tips = (
            Tip.objects.filter(status__in=("won", "lost"), created_at__gte=six_months_ago)
            .annotate(month=TruncMonth("created_at"))
            .order_by("month")
        )

        profit_by_month = defaultdict(lambda: decimal.Decimal("0"))
        for tip in recent_tips:
            profit_by_month[tip.month] += tip.profit

        max_abs = max((abs(p) for p in profit_by_month.values()), default=1) or 1
        monthly_stats = []
        for month, profit in sorted(profit_by_month.items()):
            monthly_stats.append({
                "short_name": month.strftime("%b"),
                "profit": profit,
                "height": min(abs(profit) / max_abs * 100, 100),
            })

        context = {
            "total": total,
            "won": won,
            "lost": lost,
            "win_rate": win_rate,
            "total_profit": total_profit,
            "roi": roi,
            "avg_odds": avg_odds,
            "avg_stake": avg_stake,
            "recent_form": recent_form,
            "monthly_stats": monthly_stats,
        }
        cache.set(cache_key, context, 300)

    return render(request, "predictions/stats.html", context)


@login_required
def upgrade(request):
    profile = request.user.profile
    if request.method == "POST":
        profile.upgrade_requested = True
        profile.save()
        messages.success(request, "Upgrade request submitted. Admin will review shortly.")
        return redirect("home")
    return render(request, "predictions/upgrade.html", {"profile": profile})


@login_required
def create_checkout_session(request):
    if not settings.STRIPE_SECRET_KEY:
        messages.error(request, "Payment system is temporarily unavailable.")
        return redirect("upgrade")

    try:
        session = stripe.checkout.Session.create(
            api_key=settings.STRIPE_SECRET_KEY,
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": "Matchday Pro VIP — 30 Days"},
                    "unit_amount": 2999,
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=request.build_absolute_uri("/upgrade/success/"),
            cancel_url=request.build_absolute_uri("/upgrade/"),
        )
        return redirect(session.url, status=303)
    except Exception:
        messages.error(request, "Payment initialization failed. Please try again.")
        return redirect("upgrade")


@login_required
def upgrade_success(request):
    profile = request.user.profile
    profile.is_vip = True
    profile.vip_expires_at = timezone.now() + timedelta(days=30)
    profile.save()
    cache.delete("home_page_data")
    messages.success(request, "Welcome to VIP! Your access is now active for 30 days.")
    return redirect("home")


@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError:
        return HttpResponse(status=400)
    except Exception:
        # Anything else (malformed payload structure, library errors, etc.)
        # should not surface as a 500 to Stripe - treat as a bad request so
        # Stripe's retry/alerting behaves sanely and we log it ourselves.
        logger.exception("Unexpected error verifying Stripe webhook")
        return HttpResponse(status=400)

    if event["type"] == "checkout.session.completed":
        # Stripe retries webhooks on any non-2xx response or timeout, so the
        # same event can arrive more than once. Without an idempotency check,
        # a retried event would re-grant VIP and push vip_expires_at forward
        # again on every retry. StripeEvent.id is the event's unique ID.
        event_id = event.get("id")
        if event_id and StripeEvent.objects.filter(event_id=event_id).exists():
            return HttpResponse(status=200)

        session = event["data"]["object"]
        customer_email = session.get("customer_email") or session.get("customer_details", {}).get("email")
        if customer_email:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            try:
                user = User.objects.get(email=customer_email)
                profile = user.profile
                profile.is_vip = True
                profile.vip_expires_at = timezone.now() + timedelta(days=30)
                profile.save()
                cache.delete("home_page_data")
            except User.DoesNotExist:
                logger.warning("Stripe checkout completed for unknown email: %s", customer_email)

        if event_id:
            StripeEvent.objects.create(event_id=event_id)

    return HttpResponse(status=200)


@require_POST
@ratelimit(key="ip", rate="20/m", block=True)
def betting_calculator(request):
    """JSON API for stake/odds calculation.

    Note: app.js also computes this client-side for instant feedback
    without a network round-trip. This endpoint is kept as the source of
    truth for any non-JS client (mobile app, embed widget, server-side
    integration) and for validating/auditing values server-side - it is
    intentionally not "dead code" duplicating the JS.
    """
    try:
        data = json.loads(request.body)
        stake = decimal.Decimal(str(data.get("stake", 0)))
        odds = decimal.Decimal(str(data.get("odds", 0)))
        result = {
            "stake": float(stake),
            "odds": float(odds),
            "potential_return": float(stake * odds),
            "profit": float(stake * (odds - 1)),
        }
        return JsonResponse(result)
    except Exception:
        return JsonResponse({"error": "Invalid input"}, status=400)


@ratelimit(key="ip", rate="5/h", block=True)
def register(request):
    if request.method == "POST":
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("home")
    else:
        form = CustomUserCreationForm()
    return render(request, "predictions/register.html", {"form": form})