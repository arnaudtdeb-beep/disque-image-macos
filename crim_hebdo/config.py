"""Configuration du projet.

Priorite de lecture des identifiants PISTE :
  1. variables d'environnement
  2. fichier config.json (a la racine du projet)
  3. fichier de configuration passe en CLI

Aucun mot de passe Legifrance n'est utilise : l'API PISTE s'authentifie
exclusivement par couple client_id / client_secret (OAuth2 client_credentials).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.json"

ENV_TOKEN_URL = "CRIM_HEBDO_TOKEN_URL"
ENV_API_URL = "CRIM_HEBDO_API_URL"
ENV_CLIENT_ID = "CRIM_HEBDO_CLIENT_ID"
ENV_CLIENT_SECRET = "CRIM_HEBDO_CLIENT_SECRET"


@dataclass
class LLMSettings:
    """Redacteur assistant optionnel (aucune dependance externe)."""

    provider: str = "none"  # none | openai | anthropic | ollama
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    timeout: float = 90.0
    temperature: float = 0.0
    max_output_chars: int = 2600

    @property
    def enabled(self) -> bool:
        return self.provider != "none" and bool(self.model)


@dataclass
class Config:
    # --- PISTE ---
    client_id: str = ""
    client_secret: str = ""
    token_url: str = "https://oauth.piste.gouv.fr/api/oauth/token"
    api_url: str = "https://api.piste.gouv.fr"

    # --- sources ---
    # "dila" : données ouvertes hebdomadaires, sans clé ni quota (défaut).
    # "piste" : API Judilibre, qui exige un couple client_id / client_secret.
    source: str = "dila"
    dila_base_url: str = "https://echanges.dila.gouv.fr/OPENDATA/CASS/"
    cache_dir: Path = PROJECT_ROOT / "data" / "cache"
    judilibre_base_path: str = "/cassation/judilibre/v1.0"
    use_sandbox: bool = False
    enrich_legifrance: bool = False

    # --- perimetre ---
    jurisdiction: str = "cc"
    chambers: list[str] = field(default_factory=lambda: ["crim"])
    formations: list[str] = field(default_factory=list)
    types: list[str] = field(default_factory=list)

    # --- comportement ---
    page_size: int = 50
    max_pages: int = 40
    sleep_between_calls: float = 0.25
    data_dir: Path = PROJECT_ROOT / "data"
    llm: LLMSettings = field(default_factory=LLMSettings)
    use_llm: bool = True
    only_bulletin: bool = False

    @property
    def judilibre_base(self) -> str:
        return self.api_url.rstrip("/") + self.judilibre_base_path

    @property
    def legifrance_base(self) -> str:
        return self.api_url.rstrip("/") + "/dila/legifrance/v2.4.2"

    @property
    def has_piste_credentials(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("client_secret", None)
        data["data_dir"] = str(self.data_dir)
        data["cache_dir"] = str(self.cache_dir)
        data["llm"] = {**data.get("llm", {}), "api_key": "***" if self.llm.api_key else ""}
        return data


def _from_env(env: dict[str, str]) -> dict[str, Any]:
    llm_provider = env.get("CRIM_HEBDO_LLM_PROVIDER", "").strip().lower()
    llm: dict[str, Any] = {}
    if llm_provider:
        llm = {
            "provider": llm_provider,
            "model": env.get("CRIM_HEBDO_LLM_MODEL", ""),
            "api_key": env.get("CRIM_HEBDO_LLM_API_KEY", ""),
            "base_url": env.get("CRIM_HEBDO_LLM_BASE_URL", ""),
        }
    return {
        "client_id": env.get(ENV_CLIENT_ID, ""),
        "client_secret": env.get(ENV_CLIENT_SECRET, ""),
        "token_url": env.get(ENV_TOKEN_URL, ""),
        "api_url": env.get(ENV_API_URL, ""),
        "source": env.get("CRIM_HEBDO_SOURCE", "").strip().lower(),
        "use_sandbox": env.get("CRIM_HEBDO_SANDBOX", "").lower() in {"1", "true", "yes"},
        "enrich_legifrance": env.get("CRIM_HEBDO_LEGIFRANCE", "").lower() in {"1", "true", "yes"},
        "only_bulletin": env.get("CRIM_HEBDO_ONLY_BULLETIN", "").lower() in {"1", "true", "yes"},
        "chambers": [c for c in env.get("CRIM_HEBDO_CHAMBERS", "").split(",") if c.strip()],
        "llm": llm,
    }


def _from_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_config(path: str | Path | None = None) -> Config:
    """Construit la configuration en fusionnant fichier puis environnement.

    L'environnement l'emporte sur le fichier, ce qui permet de garder les
    secrets hors du depot et de surcharger ponctuellement un parametre.
    """
    raw: dict[str, Any] = {}
    raw.update(_from_file(DEFAULT_CONFIG_PATH))
    if path:
        raw.update(_from_file(Path(path)))
    env_values = {k: v for k, v in _from_env(dict(os.environ)).items() if v not in ("", {}, [])}
    raw.update(env_values)

    if raw.get("use_sandbox"):
        raw.setdefault("token_url", "")
        raw["token_url"] = raw.get("token_url") or "https://sandbox-oauth.piste.gouv.fr/api/oauth/token"
        raw["api_url"] = raw.get("api_url") or "https://sandbox-api.piste.gouv.fr"

    llm_raw = dict(raw.pop("llm", {}) or {})
    llm = LLMSettings(**{k: v for k, v in llm_raw.items() if k in LLMSettings.__dataclass_fields__})

    known = Config.__dataclass_fields__.keys()
    kwargs: dict[str, Any] = {k: v for k, v in raw.items() if k in known}
    kwargs["llm"] = llm
    for key in ("data_dir", "cache_dir"):
        if isinstance(kwargs.get(key), str):
            kwargs[key] = Path(kwargs[key]).expanduser()
    if kwargs.get("cache_dir") == PROJECT_ROOT / "data" / "cache" and kwargs.get("data_dir"):
        kwargs["cache_dir"] = Path(kwargs["data_dir"]) / "cache"

    cfg = Config(**kwargs)
    return cfg


def save_template(path: str | Path) -> Path:
    """Ecrit un fichier de configuration commente (sans secret)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    template = {
        "_comment": (
            "Copiez ce fichier en config.json et renseignez client_id / client_secret "
            "obtenus sur https://piste.gouv.fr (ouvrir un compte, accepter les CGU de "
            "l'API Judilibre, puis Generer une cle)."
        ),
        "_source": (
            "source = 'dila' (defaut) : donnees ouvertes hebdomadaires de la Cour de "
            "cassation, sans cle ni quota. source = 'piste' : API Judilibre, qui exige un "
            "couple client_id / client_secret PISTE."
        ),
        "source": "dila",
        "client_id": "",
        "client_secret": "",
        "use_sandbox": False,
        "chambers": ["crim"],
        "enrich_legifrance": False,
        "only_bulletin": False,
        "use_llm": True,
        "llm": {
            "_comment": "provider = none | openai | anthropic | ollama",
            "provider": "none",
            "model": "",
            "api_key": "",
            "base_url": "",
        },
    }
    target.write_text(json.dumps(template, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target
