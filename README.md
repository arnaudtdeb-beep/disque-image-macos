# Veille hebdomadaire — chambre criminelle de la Cour de cassation

Outil local qui récupère chaque semaine les arrêts de la chambre criminelle,
les classe par thème de pratique, signale ceux publiés au bulletin, et rédige
pour chacun une analyse **reconstituée à partir du texte de la Cour**.

- **Source par défaut, gratuite et sans compte** : les **données ouvertes de la
  Cour de cassation** publiées par la DILA —
  <https://echanges.dila.gouv.fr/OPENDATA/CASS/>. Un fichier hebdomadaire
  `CASS_<date>.tar.gz` contient les arrêts nouvellementversés, dont tous les publiés au
  bulletin.
- **Source alternative** : l'API **Judilibre** exposée par **PISTE**
  (<https://piste.gouv.fr>), qui exige un abonnement et une clé. Elle n'est
  nécessaire pour rien ici : elle est conservée pour qui la souhaite.
- **Aucune dépendance externe** : bibliothèque standard Python uniquement.
- **Fonctionne sur macOS, Linux et Windows** avec Python 3.9 ou plus récent, et
  s'utilise **dans le navigateur** (interface locale,
  `http://127.0.0.1:8765`). Sur macOS, une **image disque `.dmg`** permet de
  lancer le programme par un double-clic, sans commande à taper (section 11) ;
  la veille hebdomadaire s'installe en une commande (section 6).
- **Aucun mot de passe n'est stocké** : par défaut, aucune authentification n'est
  requise. En source PISTE, la clé reste sur votre machine.

---

## 1. Démarrage en 2 minutes

Aucun compte, aucune clé, aucun abonnement. Prérequis : **Python 3.9 ou plus
récent**, rien d'autre.

> **Sur macOS, et sans vouloir taper de commande :** téléchargez l'image disque
> de la section 11 et double-cliquez sur `Veille criminelle.command`. Cette
> section-ci décrit la voie classique, avec deux commandes.

Sur macOS, la version fournie par le système est souvent trop ancienne. Si
`python3 --version` affiche moins de 3.9, installez-en un plus récent :

```bash
brew install python      # https://brew.sh, si Homebrew n'est pas installé
python3 --version        # doit afficher 3.9 ou plus
```

Puis, quel que soit le système, installez en une seule commande :

```bash
cd crim-hebdo

python3 tools/install.py
```

L'installateur vérifie l'environnement, écrit `config.json` (DILA par défaut),
créé les dossiers, teste l'accès aux données ouvertes, télécharge la première
veille et propose de programmer la mise à jour hebdomadaire (launchd sur macOS,
cron sur Linux). Pour l'ouvrir sans réinstaller :

```bash
python3 -m crim_hebdo serve        # ouvre http://127.0.0.1:8765
```

Ou, pour voir l'interface sans rien télécharger :

```bash
python3 tools/install.py --skip-update --no-schedule
python3 -m crim_hebdo demo && python3 -m crim_hebdo serve
```

Options utiles de l'installateur :

```bash
python3 tools/install.py --dry-run     # affiche ce qu'il ferait, ne modifie rien
python3 tools/install.py --yes         # aucune question
python3 tools/install.py --skip-update # ne télécharge pas les arrêts
python3 tools/install.py --heure 6 --minute 45   # autre créneau hebdomadaire
python3 tools/install.py --uninstall   # retire la planification
```

> Les données ouvertes DILA ne couvrent que les versions hebdomadaires encore
> conservées par la DILA (à ce jour, environ 14 mois d'historique). Les fichiers
> plus anciens ne sont pas récupérables par ce flux ; le rapport initial
> s'arrête donc à la première version disponible.

### Si vous préférez l'API Judilibre

```bash
python3 -m crim_hebdo init-config  # écrit config.json avec "source": "piste"
```

Puis <https://piste.gouv.fr/registration> : créer un compte, s'abonner à
**Judilibre** (et à **Légifrance** pour les numéros de bulletin), générer une
clé, et la copier dans `config.json`.

> **Important — vos identifiants Légifrance ne servent pas ici.**
> L'identifiant et le mot de passe du site legifrance.gouv.fr ne permettent
> aucun appel d'API. Seuls les identifiants PISTE fonctionnent. Par ailleurs,
> un mot de passe envoyé dans une conversation ou un fichier n'est plus
> considéré comme secret : il est recommandé de le changer.

---

## 2. Ce que produit l'outil

### Pour chaque arrêt

| Bloc | Contenu | Provenance |
|---|---|---|
| **L'attendu de la Cour** | Le sommaire officiel de la Cour, puis les questions qu'elle énonce elle-même (« Sur le moyen tiré de… ») | littéral |
| **La solution** | Le dispositif : rejet, cassation, renvoi | littéral |
| **Les motifs** | Les phrases de motivation portant un jugement (violation, inexactitude, absence de distinction) | littéral |
| **Les moyens du pourvoi** | Les alinéas numérotés des moyens | littéral |
| **Textes appliqués** | Le visa de l'arrêt, les articles cités | littéral |
| **Portée** | « première application », « fait divergence », novation | littéral |
| **Thèmes de veille** | nullité, détention provisoire, garde à vue… **avec les extraits qui justifient l'attribution** | déduit, justifié |
| **Publié au bulletin** | repère 📌, avec le n° de bulletin si l'enrichissement Légifrance est actif | métadonnée |
| **Matière officielle** | entrées principales du sommaire de la Cour (`DOUANES`, `PEINES`, `ACTION CIVILE`…) | littéral |

### Fidélité de la synthèse — le point important

Deux niveaux, jamais confondus :

1. **Synthèse extractive (par défaut, aucune IA requise).** L'outil ne rédige
   rien : il sélectionne des extraits du texte de la Cour et indique la zone dont
   ils proviennent. Chaque analyse est affichée avec le lien de l'arrêt et son
   ECLI. C'est le niveau de confiance maximale.

2. **Synthèse assistée par un modèle de langue (optionnel).** Le modèle doit
   renvoyer, en plus de sa rédaction, des **citations littérales**. Chaque
   citation est **vérifiée mot à mot dans le texte de l'arrêt**. Si moins de
   deux citations ne sont pas retrouvées dans le texte, le résumé est
   **abandonné** au profit de la synthèse extractive, et l'arrêt est marqué
   « à vérifier ».

Un arrêt ne peut donc pas recevoir un résumé contenant une règle de droit qui
ne figure pas dans son texte : soit la citation est retrouvée, soit le résumé
automatique est jeté.

---

## 3. Thèmes couverts

Taxonomie de pratique, **36 entrées** dans `crim_hebdo/themes.py`, regroupées en
quatre familles.

**Procédure et garanties du droit à un procès équitable**
`nullite` · `controle_legality` · `detention_provisoire` · `garde_a_vue` ·
`audition_enquete` · `droits_defense` · `duree_procedure` · `loi_dans_le_temps` ·
`droits_fondamentaux` · `vie_privee` · `presse` · `qpc`

**Déroulement du procès et offices de la juridiction**
`voies_recours` · `competence` · `juridiction` · `qualification` · `preuve` ·
`perquisition`

**Substance et sanctions**
`peines` · `sursis` · `execution_peine` · `recidive` · `stupefiants` ·
`mineurs` · `victime` · `immigration` · `escroquerie` · `cybersecurite` ·
`corruption` · `indemnisation`

**Autres matières** *(ajoutées après examen des sommaires officiels DILA)*
`douanes` · `environnement` · `urbanisme` · `circulation` · `code_special` ·
`sante`

Cette taxonomie est **distincte** de la nomenclature officielle de la Cour
(`themes_officiels`), qui est conservée et affichée telle quelle. Le classement
est déterministe : mêmes entrées, mêmes sorties, et chaque attribution est
accompagnée de ses extraits. Pour ajuster le classement, on édite la table
`THEMES` — aucun autre fichier n'est à toucher.

### Deux niveaux de détection, jamais confondus

1. **Par les motifs du texte** : un thème est retenu à partir d'exraits, et
   l'interface affiche ces extraits comme justification.
2. **Par la nomenclature officielle** : le sommaire de la Cour (`PEINES`,
   `DOUANES`, `URBANISME`…) est un indice fort. Quand il désigne une matière
   rattachée à un thème, ce thème est retenu même si les motifs ne suffisent pas
   à franchir le seuil ; la fiche indique alors « Matière officielle de la Cour :
   … » au lieu d'un extrait.

Les matières génériques (`ACTION PUBLIQUE`, `CASSATION`, `PRESCRIPTION`) sont
volontairement exclues : elles ne désignent aucune matière de fond. Le tableau
`OFFICIAL_TO_THEME` documente chaque rattachement. Sur l'import réel de
référence, **318 des 320 arrêts** reçoivent au moins un thème spécialisé, et les
36 entrées de la taxonomie sont effectivement utilisées.

---

## 4. Interface navigateur

```bash
python3 -m crim_hebdo serve          # http://127.0.0.1:8765
```

- périodes prédéfinies (7 jours, semaine dernière, 30 jours, 90 jours, tout) ;
- compteur d'arrêts, de décisions publiées au bulletin, de cassations ;
- **filtrage par thème** (combinable) et filtre « Interest particulier » ;
- recherche plein texte sur l'attendu, les motifs, les textes appliqués et le
  texte intégral ;
- fiche détaillée par arrêt, avec le **texte intégral** et la justification du
  classement thématique ;
- export **Markdown** et **JSON** de la sélection affichée ;
- « Actualiser » déclenche l'interrogation de la source configurée sans quitter
  la page (avec la source DILA, aucun identifiant n'est requis) ;
- le bandeau indique la source active : *données ouvertes DILA (gratuit)* ou PISTE.

Le serveur n'écoute que sur `127.0.0.1` : rien n'est exposé sur le réseau.

---

## 5. Ligne de commande

```bash
python3 -m crim_hebdo update                      # version DILA la plus récente
python3 -m crim_hebdo update --debut 2026-09-01 --fin 2026-09-30
python3 -m crim_hebdo update --only-bulletin      # uniquement les arrêts B
python3 -m crim_hebdo update --sans-llm           # pas de synthèse assistée
python3 -m crim_hebdo update --force              # réanalyse tout

python3 -m crim_hebdo list --debut 2026-09-01 --fin 2026-09-30
python3 -m crim_hebdo show 25-91.204
python3 -m crim_hebdo show 25-91.204 --json
python3 -m crim_hebdo themes                      # répartition thématique
python3 -m crim_hebdo export --debut ... --fin ...
python3 -m crim_hebdo check                       # accès à la source configurée

python3 -m crim_hebdo update --source piste        # Judilibre, si vous avez une clé
```

### Choix de la source

Par défaut `--source dila` : rien à configurer, l'index des versions
hebdomadaires est interrogé sur `echanges.dila.gouv.fr`. Avec `--source piste`,
l'outil utilise l'API Judilibre et exige `client_id` / `client_secret`. Les deux
sources alimentent la même base et peuvent être alternées.

Le cache DILA (`data/cache/`) conserve les archives téléchargées : une seconde
exécution ne retélécharge rien. Le supprimer force un téléchargement complet.

Les rapports sont écrits dans `data/rapports/` :

- `veille_<début>_<fin>.md` — lisible et partageable ;
- `veille_<début>_<fin>.html` — autonome, ouvrable par simple double-clic ;
- `veille_<début>_<fin>.json` — exploitable par un autre outil ;
- `dernier_veille.md` — toujours le dernier rapport produit.

Le Markdown place en tête les **arrêts publiés au bulletin**, puis la
répartition thématique, puis le détail de chaque arrêt.

---

## 6. Actualisation automatique

L'installateur de la section 1 programme déjà la veille hebdomadaire, chaque
lundi matin. Cette section décrit ce qu'il met en place, et comment agir
depuis.

### macOS (launchd)

Le job est un plist écrit dans `~/Library/LaunchAgents/`, avec le vrai dossier
de projet et votre interpréteur Python. Pour l'installer ou le modifier seul :

```bash
python3 tools/install_launchd.py
python3 tools/install_launchd.py --heure 6 --minute 45   # autre horaire
python3 tools/install_launchd.py --dry-run               # affiche sans installer
```

Le plist est écrit dans `~/Library/LaunchAgents/`. Vérification :

```bash
launchctl list | grep crimhebo
launchctl start gui/$(id -u)/com.crimhebo.veille   # déclenchement immédiat
tail -20 ~/crim-hebdo/data/logs/veille.log
```

Le job lance la veille chaque lundi à 07 h 30.

> Au premier lancement de macOS, autorisez le Python de votre choix dans
> **Réglages Système → Confidentialité et sécurité**. Sans cela, launchd refuse
> d'exécuter le job.

### Linux (cron)

L'installateur ajoute une ligne à votre crontab, encadrée par deux marqueurs
pour pouvoir la retirer sans risque :

```cron
# >>> crim-hebdo (veille chambre criminelle)
30 7 * * 1 cd /chemin/crim-hebdo && /chemin/python3 -m crim_hebdo update >> /chemin/crim-hebdo/data/logs/veille.log 2>&1
# <<< crim-hebdo
```

### Retirer la planification

Sur les deux systèmes :

```bash
python3 tools/install.py --uninstall
```

### Pourquoi le lundi matin

La Cour publie ses arrêts au fil de l'eau ; la DILA met ensuite à disposition
l'archive hebdomadaire correspondante. Une collecte le lundi matin récupère donc
la semaine complète, publications tardives comprises. En source DILA, relancer la
commande chaque semaine suffit à rester à jour : les versions déjà traitées ne
sont pas retéléchargées.

---

## 7. Synthèse assistée par IA (optionnel)

Sans configuration, l'outil fonctionne intégralement : la synthèse extractive ne
nécessite aucun modèle. Pour obtenir une rédaction plus fluide :

```jsonc
// config.json
{
  "use_llm": true,
  "llm": {
    "provider": "openai",          // openai | anthropic | ollama
    "model": "gpt-4o-mini",
    "api_key": "…",
    "base_url": ""                 // Ollama : "http://localhost:11434/v1"
  }
}
```

Les mêmes réglages sont disponibles en variables d'environnement :
`CRIM_HEBDO_LLM_PROVIDER`, `CRIM_HEBDO_LLM_MODEL`, `CRIM_HEBDO_LLM_API_KEY`,
`CRIM_HEBDO_LLM_BASE_URL`.

Règles appliquées au modèle : aucune règle de droit qui ne soit pas dans le
texte, aucune référence inventée, réponse en JSON, citations obligatoires. Les
citations sont vérifiées avant affichage.

> Les arrêts sont des documents publics (licence ouverte 2.0). En revanche,
> **n'envoyez pas le texte des arrêts à un service tiers sans vérifier ses
> conditions générales** : l'hébergement de données de justice par un
> sous-traitant relève de votre responsabilité. `provider: "none"` évite la
> question.

---

## 8. Organisation du projet

```
crim_hebdo/
  config.py        configuration (fichier + environnement)
  dila.py          données ouvertes DILA : index, archive, XML -> arrêt
  piste.py         OAuth2 PISTE, jeton mis en cache, retries
  judilibre.py     recherche, texte intégral, taxonomies
  legifrance.py    enrichissement facultatif (n° de bulletin)
  textutil.py      phrases, zones, articles, normalisation
  themes.py        taxonomie + classifieur pondéré et justifié
  summarize.py     synthèse extractive + synthèse IA vérifiée
  analysis.py      assemblage de la fiche d'arrêt
  store.py         base SQLite, dédoublonnage incrémental
  weekly.py        orchestration de la collecte
  report.py        rapports Markdown / HTML / JSON
  server.py        serveur web local
  cli.py           ligne de commande
web/               interface navigateur (aucun framework)
samples/           jeu de démonstration (données FICTIVES)
data/cache/        archives DILA téléchargées et extraites
  dila.py          données ouvertes DILA : index, téléchargement, XML
tests/             125 tests hors-ligne (dont 31 sur fixtures DILA réelles)
  test_offline.py  extraction, thèmes, synthèse, base, rapports
  test_dila.py     parsing DILA, zones, nomenclature, provenance
  test_install.py  installateur, plist launchd, crontab
  test_packaging.py assemblage de l'image disque, lanceurs, plist du serveur
  fixtures/        18 fichiers XML DILA réels (licence ouverte 2.0)
tools/             installation guidée, launchd (macOS), jeu de démo
  build_dmg.py     assemblage de l'image disque (dmgbuild, macOS)
  serve_launchd.py agent launchd du serveur web local
packaging/macos/   lanceurs double-clic et mode d'emploi mis dans l'image
.github/workflows/ construction de l'image sur un runner macOS
```

Base locale : `data/crim_hebdo.sqlite3`. Les textes intégraux y sont conservés,
ce qui évite tout nouvel appel pour un rapport déjà produit.

---

## 9. Tests

```bash
python3 -m unittest discover -s tests -v
```

Aucun test Python n'accède au réseau : ils lisent des fixtures XML réels de la
DILA conservées dans `tests/fixtures/`.

L'interface a ses propres tests, optionnels, qui chargent le vrai `web/app.js`
dans un DOM simulé pour détecter les régressions de rendu (résumé vide, fiche
qui écrase la précédente, `textContent` sur un élément absent). Ils demandent
`npm install linkedom` et un serveur en fonctionnement — voir
`tests/web/README.md`. Ils n'ajoutent aucune dépendance au projet.

---

## 10. Limites connues

- **Le classement thématique est heuristique.** Il sert à trier, pas à
  qualifier juridiquement : chaque thème est accompagné des extraits qui le
  justifient, à contrôler avant toute exploitation.
- **Un même arrêt peut recevoir plusieurs thèmes** (jusqu'à cinq), et un thème
  peut apparaître parce qu'une infraction est citée dans les faits sans être le
  cœur de l'arrêt. Le filtre « publié au bulletin » permet de prioriser.
- **Les arrêts publiés par extraits** sont signalés (`⚠️`) : leur dispositif peut
  être partiel.
- **L'enrichissement Légifrance** (numéro de bulletin) exige un abonnement
  séparé sur PISTE ; sans lui, le repère « publié au bulletin » reste disponible,
  car la source DILA porte déjà cette information.
- **Historique limité.** Le flux DILA ne sert que les versions hebdomadaires
  encore conservées : environ 14 mois au jour de la rédaction. La DILA publie par
  ailleurs un dump annuel (`Freemium_cass_global_<date>.tar.gz`, environ
  250 Mo) permettant un rattrapage, non encore automatisé ici.
- **Tous les arrêts importés en source DILA sont publiés au bulletin**, par
  construction : c'est le contenu des weekly releases. Pour suivre les arrêts non
  publiés, il faut Judilibre (`--source piste`).
- **Les quotas PISTE**, si vous retenez cette source, s'appliquent : une mise à
  jour hebdomadaire est très en deçà des limites usuelles, mais un rattrapage
  sur plusieurs mois peut demander de découper les requêtes par tranches.

---

## 11. Image disque macOS (usage par double-clic)

Pour un poste macOS destiné à une personne qui n'ouvre pas de Terminal,
`packaging/macos` fournit une **image disque `.dmg`** : un double-clic, et
l'interface s'ouvre. Rien n'y est compilé ni signé — ce sont des scripts et du
Python — donc macOS ne peut pas refuser l'ouverture, contrairement à une
application non signée.

L'image contient :

| Élément | Rôle |
|---|---|
| `Veille criminelle.command` | installe si besoin, démarre l'interface, ouvre le navigateur |
| `Arrêter la veille.command` | arrête l'interface |
| `Lisez-moi.txt` | mode d'emploi en français |
| `crim-hebdo/` (masqué) | le programme, copié dans `~/crim-hebdo` |

Au premier double-clic, le lanceur :

1. cherche un Python 3.9 ou plus récent parmi les interpréteurs usuels
   (Homebrew Apple silicon, Homebrew Intel, python.org, `PATH`) ;
2. copie le programme dans `~/crim-hebdo` — sans jamais toucher à
   `~/crim-hebdo/data` ni à `config.json` ;
3. lance `tools/install.py --yes` : configuration DILA, première veille,
   planification hebdomadaire launchd ;
4. installe un agent launchd `com.crimhebo.serve` qui garde l'interface
   disponible à chaque connexion, puis ouvre `http://127.0.0.1:8765/`.

Une version plus récente du programme remplace l'ancienne : le lanceur compare
le fichier `VERSION` (version + empreinte du code) avant de réinstaller. Vos
données et vos rapports ne sont jamais écrasés.

### Construire l'image

La création du fichier `.dmg` exige macOS (`hdiutil`), mais l'assemblage de son
contenu fonctionne partout :

```bash
python3 tools/build_dmg.py --stage-only        # n'importe quel OS : contenu seul
python3 tools/build_dmg.py                     # macOS : -> dist/Veille-criminelle-<version>.dmg
python3 tools/build_dmg.py --version 1.0.0     # version imposée
python3 tools/build_dmg.py --stage-only -o dist/stage && ls dist/stage
```

Sur macOS, dmgbuild est la seule dépendance du build (elle n'est pas nécessaire
pour utiliser l'outil) :

```bash
python3 -m pip install dmgbuild
```

Le workflow `.github/workflows/dmg.yml` fait la même chose sur un runner macOS :
il passe les tests, construit l'image, la monte pour vérifier que les lanceurs
sont toujours exécutables, puis la publie en artefact — ou l'attache à la
version publiée si le build est déclenché par un tag `v*` :

```bash
gh workflow run dmg.yml                                  # à la demande
git tag v1.0.0 && git push --tags                       # l'image rejoint la version
```

### Piloter l'interface sans l'image

L'agent du serveur se pilote directement, utile pour un poste déjà installé :

```bash
python3 tools/serve_launchd.py install      # écrit et charge l'agent
python3 tools/serve_launchd.py start        # démarre ou redémarre
python3 tools/serve_launchd.py status       # état, lisible
python3 tools/serve_launchd.py stop         # arrête
python3 tools/serve_launchd.py uninstall    # supprime l'agent
```

---

## Cadre juridique

Données issues de l'open data de la Cour de cassation et de Légifrance, sous
licence ouverte 2.0, avec attribution. Cet outil est un **outil de veille
documentaire** : il ne constitue ni une consultation juridique, ni une garantie
de l'exactitude d'une qualification. **La citation de l'arrêt fait foi** — chaque
fiche renvoie à l'ECLI, au numéro de pourvoi et au texte original.
