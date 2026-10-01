#!/bin/bash
# Arrête l'interface locale de la veille chambre criminelle.
# Le programme redémarrera seul à la prochaine connexion au Mac ; utilisez
# « python3 tools/serve_launchd.py uninstall » pour le désactiver définitivement.
set -uo pipefail

RACINE="$HOME/crim-hebdo"
AGENT="$HOME/Library/LaunchAgents/com.crimhebo.serve.plist"

printf '\033]0;Arrêt de la veille criminelle\007'
clear 2>/dev/null

titre() { printf '\n\033[1m%s\033[0m\n' "$*"; }
info() { printf '   %s\n' "$*"; }
echec() { printf '   \033[31m%s\033[0m\n' "$*" >&2; }

titre "Arrêt de l'interface"

if [ ! -f "$AGENT" ]; then
  info "L'interface n'est pas installée sur ce Mac : rien à arrêter."
  printf '\n'
  exit 0
fi

PYTHON=""
for candidat in "${CRIM_HEBDO_PYTHON:-}" \
    /opt/homebrew/bin/python3 /usr/local/bin/python3 \
    /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
    python3.14 python3.13 python3.12 python3.11 python3.10 python3.9 python3; do
  [ -n "$candidat" ] || continue
  command -v "$candidat" >/dev/null 2>&1 || continue
  if "$candidat" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
    PYTHON="$candidat"
    break
  fi
done

if [ -z "$PYTHON" ]; then
  echec "Python est introuvable : l'arrêt doit être fait depuis le Terminal."
  info "    launchctl bootout gui/\$(id -u)/com.crimhebo.serve"
  exit 1
fi

(cd "$RACINE" && "$PYTHON" tools/serve_launchd.py stop)
CODE=$?

if [ "$CODE" -ne 0 ]; then
  echec "L'arrêt a échoué. Vous pouvez fermer la fenêtre qui affiche l'interface."
  exit 1
fi

info "Vous pouvez fermer l'onglet du navigateur."
printf '\n'
