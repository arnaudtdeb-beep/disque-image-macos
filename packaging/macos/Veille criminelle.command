#!/bin/bash
# Veille chambre criminelle de la Cour de cassation.
# Lanceur double-clic : à ouvrir depuis l'image disque. Copie le programme
# dans le dossier personnel, prépare les données puis ouvre l'interface.
set -uo pipefail

RACINE="$HOME/crim-hebdo"
SOURCE="$(cd -- "$(dirname -- "$0")" 2>/dev/null && pwd)"
PORT=8765
URL="http://127.0.0.1:$PORT/"
AGENT="$HOME/Library/LaunchAgents/com.crimhebo.serve.plist"
JOURNAL="$RACINE/data/logs/serve.log"
JOURNAL_ERR="$RACINE/data/logs/serve.err.log"

printf '\033]0;Veille chambre criminelle\007'
clear 2>/dev/null

titre() { printf '\n\033[1m%s\033[0m\n' "$*"; }
info() { printf '   %s\n' "$*"; }
alerte() { printf '   \033[33m%s\033[0m\n' "$*"; }
echec() { printf '   \033[31m%s\033[0m\n' "$*" >&2; }
attente() { printf '\n   Appuyez sur Entrée pour fermer cette fenêtre.'; read -r _; }

python_valide() {
  [ -n "$1" ] || return 1
  command -v "$1" >/dev/null 2>&1 || return 1
  "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null
}

trouve_python() {
  for candidat in "${CRIM_HEBDO_PYTHON:-}" \
      /opt/homebrew/bin/python3 /usr/local/bin/python3 \
      /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
      python3.14 python3.13 python3.12 python3.11 python3.10 python3.9 python3; do
    if python_valide "$candidat"; then
      printf '%s' "$candidat"
      return 0
    fi
  done
  return 1
}

installe_projet() {
  local d
  mkdir -p "$RACINE" || return 1
  for d in crim_hebdo web tools samples tests; do
    rm -rf "${RACINE:?}/$d"
    cp -R "$SOURCE/crim-hebdo/$d" "$RACINE/$d" || return 1
  done
  cp -p "$SOURCE/crim-hebdo/config.example.json" "$RACINE/config.example.json"
  cp -p "$SOURCE/crim-hebdo/README.md" "$RACINE/README.md"
  [ -f "$SOURCE/crim-hebdo/VERSION" ] && cp -p "$SOURCE/crim-hebdo/VERSION" "$RACINE/VERSION"
  find "$RACINE" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null
  return 0
}

version_differente() {
  local d source
  d="$RACINE/VERSION"
  source="$SOURCE/crim-hebdo/VERSION"
  [ -f "$source" ] || return 1
  [ -f "$d" ] || return 0
  ! cmp -s "$source" "$d"
}

titre "1. Recherche de Python"
PYTHON="$(trouve_python)"
if [ -z "$PYTHON" ]; then
  echec "Python 3.9 ou plus récent est nécessaire, et n'a pas été trouvé."
  info ""
  info "Pour l'installer, le plus simple est d'ouvrir le site de Python :"
  info "    https://www.python.org/downloads/macos/"
  info "puis de relancer ce fichier. L'installation demande un mot de passe"
  info "que vous seul connaissez, et ne concerne que votre compte."
  open "https://www.python.org/downloads/macos/" 2>/dev/null
  attente
  exit 1
fi
info "Python trouvé : $("$PYTHON" -c 'import platform;print(platform.python_version())')"

titre "2. Installation du programme"
if [ ! -f "$RACINE/tools/install.py" ] || version_differente; then
  info "Copie dans $RACINE"
  if ! installe_projet >/dev/null; then
    echec "La copie a échoué."
    info "Le disque image est-il encore monté ? Si le dossier n'est pas visible,"
    info "ouvrez à nouveau le fichier .dmg puis double-cliquez ce lanceur."
    attente
    exit 1
  fi
  info "Programme à jour."
else
  info "Déjà installé dans $RACINE"
fi

if [ ! -f "$RACINE/.premier_lancement" ]; then
  titre "3. Préparation (une seule fois)"
  alerte "Le premier téléchargement des arrêts peut prendre quelques minutes."
  info "Laissez cette fenêtre ouverte jusqu'au message « c'est prêt »."
  (cd "$RACINE" && "$PYTHON" tools/install.py --yes --port "$PORT")
  touch "$RACINE/.premier_lancement"
fi

titre "4. Démarrage de l'interface"
if [ -f "$AGENT" ]; then
  (cd "$RACINE" && "$PYTHON" tools/serve_launchd.py start --port "$PORT")
else
  (cd "$RACINE" && "$PYTHON" tools/serve_launchd.py install --port "$PORT")
fi
CODE=$?
if [ "$CODE" -ne 0 ]; then
  titre "Le programme n'a pas démarré"
  echec "Le journal technique est ci-dessous."
  [ -f "$JOURNAL_ERR" ] && tail -n 20 "$JOURNAL_ERR"
  info ""
  info "Si le message évoque Python et les réglages du Mac :"
  info "Réglages Système → Confidentialité et sécurité → autorisez Python."
  attente
  exit 1
fi

info "Ouverture de $URL"
open "$URL" 2>/dev/null

titre "C'est prêt"
info "L'interface s'ouvre dans votre navigateur."
info "Vous pouvez fermer cette fenêtre : le programme continue de tourner"
info "tout seul, et rouvrira l'interface à la prochaine connexion au Mac."
info ""
info "Vos données et vos rapports : $RACINE/data"

while :; do
  printf '\n   [Entrée] fermer    [J] journal    [M] mettre à jour maintenant\n   > '
  read -r choix || break
  case "$choix" in
    ""|q|Q|exit) break ;;
    j|J) tail -n 25 "$JOURNAL" 2>/dev/null || info "journal introuvable : $JOURNAL" ;;
    m|M) (cd "$RACINE" && "$PYTHON" -m crim_hebdo update) ;;
    a|A) open "$URL" ;;
    *) info "Option inconnue." ;;
  esac
done

printf '\n   À bientôt.\n\n'
