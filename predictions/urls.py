from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("tips/<str:tip_type>/", views.tips_list, name="tips_list"),
    path("tips/detail/<int:pk>/", views.tip_detail, name="tip_detail"),
    path("history/", views.history, name="history"),
    path("stats/", views.stats, name="stats"),
    path("upgrade/", views.upgrade, name="upgrade"),
    path("upgrade/checkout/", views.create_checkout_session, name="checkout"),
    path("upgrade/success/", views.upgrade_success, name="upgrade_success"),
    path("stripe/webhook/", views.stripe_webhook, name="stripe_webhook"),
    path("api/calculator/", views.betting_calculator, name="calculator"),
    path("register/", views.register, name="register"),
]