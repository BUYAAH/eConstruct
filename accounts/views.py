import msal
from django.conf import settings
from django.contrib.auth import get_user_model, login as auth_login
from django.shortcuts import redirect, render

from core.models import Company

from .microsoft import build_msal_app, save_cache

User = get_user_model()

SESSION_FLOW_KEY = "msal_auth_flow"


def login_view(request):
    """Kick off the Microsoft auth-code flow (no local login page)."""
    app = build_msal_app()
    flow = app.initiate_auth_code_flow(
        settings.GRAPH_SCOPES, redirect_uri=settings.MS_REDIRECT_URI
    )
    request.session[SESSION_FLOW_KEY] = flow
    return redirect(flow["auth_uri"])


def callback(request):
    flow = request.session.pop(SESSION_FLOW_KEY, None)
    if flow is None:
        return redirect("accounts:login")

    cache = msal.SerializableTokenCache()
    app = build_msal_app(cache)
    try:
        result = app.acquire_token_by_auth_code_flow(flow, request.GET.dict())
    except ValueError:
        return render(request, "accounts/login_error.html", status=400)
    if "error" in result:
        return render(
            request,
            "accounts/login_error.html",
            {"error": result.get("error_description")},
            status=400,
        )

    claims = result["id_token_claims"]
    oid = claims["oid"]
    tenant_id = claims["tid"]

    user = User.objects.filter(ms_object_id=oid).first()
    if user is None:
        company = Company.objects.filter(ms_tenant_id=tenant_id, is_active=True).first()
        if company is None:
            return render(
                request,
                "accounts/no_company.html",
                {"tenant_id": tenant_id},
                status=403,
            )
        email = claims.get("preferred_username", "")
        name_parts = (claims.get("name") or "").split(" ", 1)
        user = User.objects.create(
            username=oid,
            email=email,
            first_name=name_parts[0],
            last_name=name_parts[1] if len(name_parts) > 1 else "",
            company=company,
            ms_object_id=oid,
        )

    if not user.is_active or user.company is None or not user.company.is_active:
        return render(request, "accounts/no_company.html", status=403)

    auth_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    save_cache(user, cache)
    return redirect(settings.LOGIN_REDIRECT_URL)
