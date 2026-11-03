"""Contexte TLS pour les appels HTTPS sortants (PISTE, Légifrance).

Par défaut, on utilise la vérification standard de Python. Deux variables
d'environnement permettent de s'adapter à un réseau particulier, SANS jamais
désactiver la vérification par défaut :

  CRIM_HEBDO_CA_BUNDLE     chemin d'un fichier PEM d'autorité de certification
                           à ajouter à la vérification. Utile quand un proxy
                           (entreprise, antivirus, établissement scolaire)
                           intercepte le HTTPS avec son propre certificat racine.

  CRIM_HEBDO_SSL_NO_VERIFY =1 (ou true/yes) : désactive la vérification du
                           certificat, en DERNIER RECOURS. À réserver à une
                           machine personnelle sur un réseau de confiance : cela
                           supprime la protection contre l'interception.
"""

from __future__ import annotations

import os
import ssl


def _verif_desactivee() -> bool:
    return os.environ.get("CRIM_HEBDO_SSL_NO_VERIFY", "").strip().lower() in {
        "1", "true", "yes", "oui", "on",
    }


def ssl_context() -> ssl.SSLContext:
    """Contexte TLS adapté à la configuration de la machine."""
    if _verif_desactivee():
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context

    bundle = os.environ.get("CRIM_HEBDO_CA_BUNDLE", "").strip()
    if bundle:
        # load_verify_locations AJOUTE l'autorité fournie à celles du système :
        # les sites déjà valides continuent de fonctionner.
        context = ssl.create_default_context()
        try:
            context.load_verify_locations(cafile=os.path.expanduser(bundle))
        except (OSError, ssl.SSLError) as exc:
            raise RuntimeError(
                f"CRIM_HEBDO_CA_BUNDLE pointe vers un fichier inutilisable ({bundle}) : {exc}"
            ) from exc
        return context

    return ssl.create_default_context()
