class SecurityHeadersMiddleware:
    """Apply a conservative browser-security baseline to every dynamic response."""

    POLICY = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https:; "
        "style-src 'self' 'unsafe-inline' https:; "
        "img-src 'self' data: blob: https:; "
        "font-src 'self' data: https:; "
        "connect-src 'self' https:; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault('Content-Security-Policy', self.POLICY)
        response.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=(), payment=()')
        response.setdefault('X-Content-Type-Options', 'nosniff')
        return response
