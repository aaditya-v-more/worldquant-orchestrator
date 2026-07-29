"""Authenticated, rate-governed HTTP session against the BRAIN API.

Design notes:

* The session cookie is persisted to disk and reused across process runs. This
  matters: re-authenticating on every invocation is both slow and the most
  abnormal-looking traffic pattern a client can produce.
* HTTP Basic credentials are sent to ``POST /authentication`` and nowhere else.
* A 401 on any call triggers exactly one silent re-auth, then the original
  request is replayed. No retry storms.
* Biometric (Persona) verification is never bypassed. When BRAIN asks for it,
  the flow stops and hands the URL to the human.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any, Optional

import requests

from . import config, endpoints
from .pacing import RateGovernor, is_retryable


class AuthError(RuntimeError):
    pass


class BiometricRequired(AuthError):
    """BRAIN wants a Persona identity check completed by a human in a browser."""

    def __init__(self, inquiry_url: str, payload: dict):
        super().__init__(
            "biometric verification required — complete it in a browser, then "
            "run: python -m wqo auth persona\n  " + inquiry_url
        )
        self.inquiry_url = inquiry_url
        self.payload = payload


class ApiError(RuntimeError):
    def __init__(self, message: str, response: Optional[requests.Response] = None):
        super().__init__(message)
        self.response = response
        self.status_code = response.status_code if response is not None else None


def load_credentials(path: Optional[Path] = None) -> tuple[str, str]:
    path = Path(path) if path else config.CREDENTIALS_PATH
    if not path.exists():
        raise AuthError(
            f"credentials file not found: {path}\n"
            'Create it yourself with: {"email": "...", "password": "..."}\n'
            "then run: chmod 600 " + str(path)
        )
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise AuthError(f"credentials file is not valid JSON: {path} ({exc})") from exc

    if isinstance(data, list) and len(data) == 2:  # [email, password] form
        email, password = data
    else:
        email = data.get("email") or data.get("username")
        password = data.get("password")
    if not email or not password:
        raise AuthError(f"credentials file must contain 'email' and 'password': {path}")
    return str(email), str(password)


def _write_private(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600


class BrainSession(requests.Session):
    def __init__(
        self,
        *,
        credentials_path: Optional[Path] = None,
        session_path: Optional[Path] = None,
        pacing: Optional[config.Pacing] = None,
        verbose: bool = False,
    ):
        super().__init__()
        self.credentials_path = credentials_path
        self.session_path = Path(session_path) if session_path else config.SESSION_PATH
        self.governor = RateGovernor(pacing or config.PACING)
        self.verbose = verbose
        self.headers.update(
            {
                "User-Agent": config.USER_AGENT,
                "Accept": "application/json",
            }
        )
        self._authenticating = False
        self._load_cookies()

    # -- cookie persistence -----------------------------------------------

    def _load_cookies(self) -> None:
        if not self.session_path.exists():
            return
        try:
            saved = json.loads(self.session_path.read_text())
        except (OSError, json.JSONDecodeError):
            return
        for name, value in (saved.get("cookies") or {}).items():
            self.cookies.set(name, value, domain=".worldquantbrain.com")

    def _save_cookies(self) -> None:
        _write_private(
            self.session_path,
            {"cookies": requests.utils.dict_from_cookiejar(self.cookies)},
        )

    def forget(self) -> None:
        self.cookies.clear()
        if self.session_path.exists():
            self.session_path.unlink()

    # -- core request path -------------------------------------------------

    def request(  # type: ignore[override]
        self,
        method: str,
        url: str,
        *,
        allow_reauth: bool = True,
        **kwargs,
    ) -> requests.Response:
        url = endpoints.absolute(url)
        kwargs.setdefault("timeout", config.PACING.http_timeout)

        attempt = 0
        reauthed = False
        while True:
            attempt += 1
            self.governor.wait_turn()
            try:
                response = super().request(method, url, **kwargs)
            except requests.RequestException as exc:
                if attempt > config.PACING.max_retries:
                    raise ApiError(f"{method} {url} failed: {exc}") from exc
                self.governor.sleep_backoff(attempt)
                continue

            if self.verbose:
                print(f"[wqo] {method} {url} -> {response.status_code}")

            if (
                response.status_code == 401
                and allow_reauth
                and not reauthed
                and not self._authenticating
                and not url.endswith(endpoints.AUTHENTICATION)
            ):
                reauthed = True
                self.authenticate()
                continue

            if is_retryable(response):
                if attempt > config.PACING.max_retries:
                    raise ApiError(
                        f"{method} {url} still {response.status_code} after "
                        f"{attempt} attempts",
                        response,
                    )
                # A 429 usually carries Retry-After; honor it over our own guess.
                if response.status_code == 429:
                    self.governor.sleep_retry_after(response, default=None)
                else:
                    self.governor.sleep_backoff(attempt)
                continue

            return response

    # -- authentication ----------------------------------------------------

    def authenticate(self) -> dict:
        """Log in with HTTP Basic and persist the resulting session cookie."""
        email, password = load_credentials(self.credentials_path)
        self._authenticating = True
        try:
            response = self.request(
                "POST",
                endpoints.AUTHENTICATION,
                auth=(email, password),
                allow_reauth=False,
            )
        finally:
            self._authenticating = False

        payload: Any = {}
        if response.content:
            try:
                payload = response.json()
            except ValueError:
                payload = {}

        if isinstance(payload, dict) and "inquiry" in payload:
            config.ensure_data_dir()
            _write_private(config.PENDING_PERSONA_PATH, payload)
            inquiry_url = (
                f"{endpoints.API_ROOT}{endpoints.AUTHENTICATION}"
                f"/persona?inquiry={payload['inquiry']}"
            )
            raise BiometricRequired(inquiry_url, payload)

        if response.status_code not in (200, 201):
            raise AuthError(
                f"authentication failed ({response.status_code}): {response.text[:400]}"
            )

        self._save_cookies()
        if config.PENDING_PERSONA_PATH.exists():
            config.PENDING_PERSONA_PATH.unlink()
        return payload if isinstance(payload, dict) else {}

    def complete_persona(self) -> dict:
        """Finish a biometric check the human has already done in a browser."""
        if not config.PENDING_PERSONA_PATH.exists():
            raise AuthError(
                "no pending biometric check — run: python -m wqo auth login"
            )
        payload = json.loads(config.PENDING_PERSONA_PATH.read_text())
        response = self.request(
            "POST", endpoints.AUTHENTICATION_PERSONA, json=payload, allow_reauth=False
        )
        if response.status_code not in (200, 201):
            raise AuthError(
                "biometric verification not accepted "
                f"({response.status_code}): {response.text[:400]}\n"
                "Make sure you completed the Persona flow in your browser first."
            )
        self._save_cookies()
        config.PENDING_PERSONA_PATH.unlink()
        # Re-auth so the session cookie reflects the verified state.
        return self.authenticate()

    def logged_in(self) -> bool:
        response = self.request(
            "GET", endpoints.AUTHENTICATION, allow_reauth=False
        )
        return response.status_code in (200, 201)

    def ensure_auth(self) -> None:
        """Authenticate only if the cached cookie is not already good."""
        if self.cookies and self.logged_in():
            return
        self.authenticate()

    def logout(self) -> None:
        try:
            self.request("DELETE", endpoints.AUTHENTICATION, allow_reauth=False)
        except ApiError:
            pass
        self.forget()

    # -- convenience -------------------------------------------------------

    def json(self, method: str, url: str, **kwargs) -> Any:
        """Request and decode JSON, raising :class:`ApiError` on failure."""
        response = self.request(method, url, **kwargs)
        if response.status_code >= 400:
            raise ApiError(
                f"{method} {url} -> {response.status_code}: {response.text[:400]}",
                response,
            )
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise ApiError(f"{method} {url} returned non-JSON body", response) from exc

    def whoami(self) -> dict:
        return self.json("GET", endpoints.USERS_SELF)


def open_session(*, verbose: bool = False, authenticate: bool = True) -> BrainSession:
    """Build a session and make sure it is usable."""
    session = BrainSession(verbose=verbose)
    if authenticate:
        session.ensure_auth()
    return session
