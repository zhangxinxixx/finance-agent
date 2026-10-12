"""Official public FedWatch tables through their observed ASP.NET form action.

Anonymous form/session parameters stay inside the HTTP client and archived HTML;
neither logs nor public source URLs expose them. No probabilities are inferred.
"""
from html.parser import HTMLParser
import re
import time
from urllib.parse import urljoin, urlsplit

from curl_cffi import CurlOpt, CurlHttpVersion, requests

from apps.collectors.macro.fedwatch_browser import BrowserCaptureError, collect_fedwatch_pages

VIEW_URL = "https://cmegroup-tools.quikstrike.net/User/QuikStrikeView.aspx?viewitemid=IntegratedFedWatchTool"
PARENT_URL = "https://www.cmegroup.cn/fed-watch/"
MAX_BYTES = 4 * 1024 * 1024


class _Form(HTMLParser):
    def __init__(self, body):
        super().__init__(convert_charrefs=True)
        self.action, self.fields, self.tabs = None, {}, []
        self.in_form = False
        self.feed(body)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form" and self.action is None:
            self.action = attrs.get("action", "")
            self.in_form = True
        elif self.in_form and tag == "input" and attrs.get("type", "").lower() == "hidden" and attrs.get("name"):
            self.fields[attrs["name"]] = attrs.get("value", "")
        elif self.in_form and tag == "a" and "lbMeeting" in attrs.get("id", ""):
            match = re.fullmatch(r"javascript:__doPostBack\('([\w$]+)',''\);?", attrs.get("href", ""))
            if match:
                self.tabs.append(match[1])

    def handle_endtag(self, tag):
        if tag == "form":
            self.in_form = False


def _form_url(base, action, *, anonymous_redirect=False):
    url = urljoin(base, action)
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != "cmegroup-tools.quikstrike.net"
            or parsed.port not in (None, 443) or parsed.username or parsed.password
            or parsed.path not in ({"/User/QuikStrikeView.aspx", "/Account/Login.aspx"}
                                   if anonymous_redirect else {"/User/QuikStrikeView.aspx"})):
        raise BrowserCaptureError("untrusted_form_action")
    return url


def capture_webforms(*, client=None, http1=False):
    owned = client is None
    if owned:
        options = {CurlOpt.PROXY: ""}
        if http1:
            options[CurlOpt.HTTP_VERSION] = CurlHttpVersion.V1_1
        client = requests.Session(impersonate="chrome", trust_env=False, curl_options=options)
    deadline = time.monotonic() + 90
    pages, raw_pages, tabs, errors = [], [], [], []

    def fetch(method, url, *, redirects=0, **kwargs):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise BrowserCaptureError("capture_deadline")
        try:
            response = client.request(method, url, timeout=min(15, remaining),
                                      allow_redirects=False, stream=True, **kwargs)
            try:
                chunks, size = [], 0
                for chunk in response.iter_content():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise BrowserCaptureError("response_too_large")
                    chunks.append(chunk)
                body = b"".join(chunks)
                from apps.collectors.macro.fedwatch_free import _safe_public_url
                raw_pages.append({"body": body, "http_status": response.status_code,
                                  "source_url": _safe_public_url(url)})
                if response.status_code in (301, 302, 303, 307, 308):
                    if redirects >= 3:
                        raise BrowserCaptureError("redirect_limit")
                    # Never forward hidden form state outside the known public
                    # view. The initial GET uses a normal anonymous redirect.
                    if response.status_code in (301, 302, 303):
                        method = "GET"
                        kwargs.pop("data", None)
                    # The public tool initializes its anonymous session via a
                    # GET redirect through /Account/Login.aspx. Never submit a
                    # login form, credentials or POST state to that endpoint.
                    target = _form_url(url, response.headers.get("Location", ""),
                                       anonymous_redirect=method == "GET")
                    response.close()
                    return fetch(method, target, redirects=redirects + 1, **kwargs)
                if response.status_code != 200:
                    raise BrowserCaptureError("http_status_" + str(response.status_code))
                return body.decode("utf-8-sig"), url
            finally:
                response.close()
        except requests.RequestsError as exc:
            raise BrowserCaptureError("transport_curl_" + str(int(exc.code))) from None

    try:
        url = VIEW_URL
        body, url = fetch("GET", url, headers={"Referer": PARENT_URL})
        form = _Form(body)
        if not 1 <= len(form.tabs) <= 16 or "__VIEWSTATE" not in form.fields:
            raise BrowserCaptureError("official_form_unavailable")
        tabs = list(form.tabs)
        # Submit even the first tab: never assume which meeting the GET selected.
        for target in tabs:
            try:
                form = _Form(body)
                if target not in form.tabs or "__VIEWSTATE" not in form.fields:
                    raise BrowserCaptureError("meeting_form_changed")
                action = _form_url(url, form.action)
                fields = {**form.fields, "__EVENTTARGET": target, "__EVENTARGUMENT": ""}
                body, url = fetch("POST", action, data=fields, headers={"Referer": url})
                pages.append({"html": body, "http_status": 200})
            except (BrowserCaptureError, ValueError) as exc:
                errors.append({"reason": str(exc) if isinstance(exc, BrowserCaptureError) else "invalid_form"})
                break
    except (BrowserCaptureError, ValueError) as exc:
        errors.append({"reason": str(exc) if isinstance(exc, BrowserCaptureError) else "invalid_form"})
    finally:
        if owned:
            client.close()
    return {"pages": pages, "raw_pages": raw_pages, "meeting_tabs": len(tabs), "errors": errors,
            "reason": errors[0]["reason"] if errors else None}


def collect_fedwatch_webforms(*, storage_root, now=None, client=None, http1=False):
    result = collect_fedwatch_pages(storage_root=storage_root, now=now,
                                   capture=lambda: capture_webforms(client=client, http1=http1),
                                   transport="curl_cffi_webforms", capture_kind="http_response")
    result['connection_profile'] = 'chrome_http1_direct' if http1 else 'chrome_direct'
    return result
