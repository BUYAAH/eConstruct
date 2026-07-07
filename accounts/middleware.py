from django.shortcuts import redirect

from .microsoft import ReauthRequired


class ReauthRequiredMiddleware:
    """When a Graph token can't be refreshed silently, send the user back
    through Microsoft login instead of showing a 500."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, ReauthRequired):
            return redirect("accounts:login")
        return None
