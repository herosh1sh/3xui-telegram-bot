from django.urls import path
from . import views

urlpatterns = [
    path("", views.spa),
    path("cabinet", views.spa),
    path("admin", views.spa),
    path("auth", views.auth),
    path("api/telegram", views.telegram_config),
    path("auth/telegram", views.telegram_login),
    path("api/me", views.me),
    path("api/topup", views.topup),
    path("api/check", views.check),
    path("api/buy", views.buy),
    path("api/trial", views.trial),
    path("api/promo", views.promo),
    path("api/admin/overview", views.overview),
    path("api/admin/users", views.users),
    path("api/admin/balance", views.admin_balance),
    path("api/admin/sub", views.admin_sub),
    path("api/admin/promo", views.admin_promo),
    path("api/admin/announce", views.announce),
]
