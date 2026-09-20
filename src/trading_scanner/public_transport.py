"""Paced public HTTP boundaries; no raw request/header data enters feedback."""
from urllib.parse import urljoin, urlsplit
import urllib.request
import urllib.error
from .core import DataError


def read_constituents(url, governor):
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    def request():
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'MomentumResearch/0.1 (personal research)'})
            with urllib.request.build_opener(NoRedirect()).open(req, timeout=30) as response:
                governor.observe(response.status, response.headers.get('Retry-After'))
                return response.read(4_000_001)
        except urllib.error.HTTPError as exc:
            governor.observe(exc.code, (exc.headers or {}).get('Retry-After'))
            raise DataError('PUBLIC_ACCESS_REJECTED' if exc.code in (401, 403) else 'PUBLIC_RATE_LIMITED' if exc.code == 429 else 'PUBLIC_HTTP_ERROR') from None
        except OSError:
            raise DataError('PUBLIC_NETWORK_ERROR') from None
    return governor.call(request)


def session_class(base, governor):
    """Subclass the supported session: catches library retries and consent calls.

    Redirects are followed explicitly, one paced request per hop, only within
    Yahoo's HTTPS hosts. No proxy/cookie/header inspection or persistence here.
    """
    class GovernedSession(base):
        # Some backends bind convenience methods to the base request method.
        # Explicit dispatch keeps their GET/POST calls inside the shared gate.
        def get(self, url, **kwargs):
            return self.request("GET", url, **kwargs)

        def post(self, url, **kwargs):
            return self.request("POST", url, **kwargs)

        def request(self, method, url, *args, **kwargs):
            method = method.upper()
            kwargs['allow_redirects'] = False
            for _ in range(6):
                parsed = urlsplit(url)
                if parsed.scheme != 'https' or not parsed.hostname or not (parsed.hostname == 'yahoo.com' or parsed.hostname.endswith('.yahoo.com')):
                    governor.blocked = 'PUBLIC_ACCESS_REJECTED'
                    raise DataError(governor.blocked)
                def operation():
                    try:
                        response = super(GovernedSession, self).request(method, url, *args, **kwargs)
                    except Exception:
                        raise DataError('PUBLIC_NETWORK_ERROR') from None
                    status = response.status_code
                    governor.observe(status, response.headers.get('Retry-After'))
                    if status in (401, 403, 429, 500, 502, 503, 504):
                        response.close()
                        raise DataError('PUBLIC_ACCESS_REJECTED' if status in (401, 403) else 'PUBLIC_RATE_LIMITED' if status == 429 else 'PUBLIC_HTTP_ERROR')
                    return response
                response = governor.call(operation, retries=1 if method == 'GET' else 0)
                if response.status_code not in (301, 302, 303, 307, 308):
                    return response
                location = response.headers.get('Location')
                response.close()
                if not isinstance(location, str) or len(location) > 8192:
                    governor.blocked = 'PUBLIC_HTTP_ERROR'
                    raise DataError(governor.blocked)
                url = urljoin(url, location)
                kwargs.pop('params', None)
                if response.status_code == 303 or response.status_code in (301, 302) and method == 'POST':
                    method = 'GET'
                    kwargs.pop('data', None)
                    kwargs.pop('json', None)
            governor.blocked = 'PUBLIC_HTTP_ERROR'
            raise DataError(governor.blocked)
    return GovernedSession


def make_yahoo_session(governor):
    # Reviewed against the pinned yfinance 1.7.0 backend compatibility interface.
    from yfinance import _http
    cls = session_class(_http.requests.Session, governor)
    return cls(**({'impersonate': 'chrome'} if _http.HAS_CURL_CFFI else {}))
