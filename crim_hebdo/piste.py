"""Authentification OAuth2 PISTE et couche HTTP.

Flux PISTE (identique pour l'API Legifrance et l'API Judilibre) :

    POST https://oauth.piste.gouv.fr/api/oauth/token
    Content-Type: application/x-www-form-urlencoded
    grant_type=client_credentials & client_id=... & client_secret=... & scope=openid

    -> {"access_token": "...", "token_type": "Bearer", "expires_in": 3600}

Chaque appel met ensuite l'en-tete Authorization: Bearer <token>.
Le jeton est mis en cache en memoire jusqu'a expiration (marge de securite).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from .config import Config

USER_AGENT = "crim-hebdo/1.0 (+veille chambre criminelle; usage professionnel)"


class PisteError(RuntimeError):
    """Erreur d'authentification ou d'appel sur PISTE."""

    def __init__(self, message: str, status: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


class MissingCredentials(PisteError):
    pass


@dataclass
class _Token:
    value: str
    expires_at: float

    def valid(self) -> bool:
        return bool(self.value) and time.time() < self.expires_at


class PisteClient:
    """Client HTTP minimaliste (bibliotheque standard uniquement)."""

    def __init__(self, config: Config):
        if not config.has_piste_credentials:
            raise MissingCredentials(
                "Identifiants PISTE absents. Créez un compte gratuit sur "
                "https://piste.gouv.fr/registration, acceptez les CGU de l'API "
                "Judilibre, générez une clé puis renseignez client_id / client_secret "
                "dans config.json (ou via les variables d'environnement "
                "CRIM_HEBDO_CLIENT_ID / CRIM_HEBDO_CLIENT_SECRET)."
            )
        self.config = config
        self._token: _Token | None = None

    # ------------------------------------------------------------------ oauth
    def token(self, force: bool = False) -> str:
        if not force and self._token and self._token.valid():
            return self._token.value

        data = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
                "scope": "openid",
            }
        ).encode()
        request = urllib.request.Request(
            self.config.token_url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:500]
            hint = ""
            if exc.code in (400, 401):
                hint = " Verifiez client_id / client_secret et que l'API est bien activee sur votre compte PISTE."
            raise PisteError(
                f"Authentification PISTE refusee (HTTP {exc.code}){hint} Detail : {body}",
                status=exc.code,
                payload=body,
            ) from exc
        except urllib.error.URLError as exc:
            raise PisteError(f"Endpoint OAuth PISTE injoignable ({self.config.token_url}) : {exc.reason}") from exc

        access_token = payload.get("access_token")
        if not access_token:
            raise PisteError(f"Reponse OAuth inattendue (pas de access_token) : {payload}", payload=payload)

        expires_in = int(payload.get("expires_in") or 3600)
        self._token = _Token(access_token, time.time() + max(60, expires_in - 90))
        return access_token

    # ------------------------------------------------------------------- http
    def request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        timeout: float = 45.0,
        retries: int = 3,
    ) -> Any:
        if params:
            cleaned = {k: _flatten_param(v) for k, v in params.items() if v not in (None, [], (), "")}
            if cleaned:
                url = f"{url}?{urllib.parse.urlencode(cleaned, doseq=True)}"

        body = None
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        if json_body is not None:
            body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"

        last_error: Exception | None = None
        for attempt in range(1, retries + 1):
            request = urllib.request.Request(url, data=body, method=method.upper(), headers=headers)
            request.add_header("Authorization", f"Bearer {self.token()}")
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    raw = response.read().decode("utf-8")
                    return json.loads(raw) if raw.strip() else {}
            except urllib.error.HTTPError as exc:
                raw = exc.read().decode("utf-8", "replace")
                if exc.code == 401 and attempt < retries:
                    self._token = None  # jeton expire prematurely : on relit
                    last_error = exc
                    time.sleep(0.6 * attempt)
                    continue
                if exc.code in (429, 502, 503, 504) and attempt < retries:
                    backoff = 1.5 * (2 ** (attempt - 1))
                    time.sleep(backoff)
                    last_error = exc
                    continue
                raise PisteError(
                    f"Appel PISTE en echec {method.upper()} {url} (HTTP {exc.code}) : {raw[:400]}",
                    status=exc.code,
                    payload=raw,
                ) from exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < retries:
                    time.sleep(1.2 * attempt)
                    continue
        raise PisteError(f"Appel PISTE en echec {method.upper()} {url} apres {retries} tentatives : {last_error}")

    def get(self, url: str, params: dict[str, Any] | None = None, timeout: float = 45.0) -> Any:
        return self.request("GET", url, params=params, timeout=timeout)


def _flatten_param(value: Any) -> Any:
    """PISTE attend des parametres repetes (chamber=crim&chamber=civ1)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return value
