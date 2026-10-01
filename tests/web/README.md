# Tests de l'interface

Ces deux scripts chargent le **vrai** `web/index.html` et le **vrai**
`web/app.js` dans un DOM minimal, avec un `fetch` qui interroge un serveur en
fonctionnement. Ils attrapent les régressions de rendu que la suite Python ne
peut pas voir : un résumé vide, une fiche qui écrase celle d'avant, un
`something.textContent` sur un élément absent.

Ils ne font **pas** partie de la suite Python et n'ajoutent aucune dépendance au
projet. Ils exigent `linkedom` et un serveur démarré.

## Préparation

```bash
# 1. le serveur doit tourner
python3 -m crim_hebdo serve --port 8765 --no-browser

# 2. dans un autre terminal
cd tests/web
npm install linkedom
node test_app.mjs        # rendu des fiches
node test_filters.mjs    # filtres, recherche, export
```

Sans `linkedom`, les scripts signorent et rendent la main avec le code 0.

## Ce qui est vérifié

`test_app.mjs` — le chargement ne produit aucune erreur, les compteurs sont
numériques, chaque fiche porte son « attendu », sa solution, ses motifs, ses
textes appliqués, et son texte intégral. Un point clé : les « attendus » de
deux fiches différentes ne sont pas identiques, ce qui détecte le bug où tous les
résumés s'empilaient sur la première fiche.

`test_filters.mjs` — le filtre « publié au bulletin », la recherche plein texte,
le message « aucun arrêt ne correspond », le changement de période, et
l'export Markdown.

## Port différent

```bash
BASE=http://127.0.0.1:8899 node test_app.mjs
```

## Portée et limite

Un DOM simulé n'est pas un navigateur. Ces tests vérifient la logique de rendu
et l'absence d'exceptions, pas la mise en page ni le comportement d'un vrai
navigateur sur toutes les plateformes. Pour cela, ouvrez
`http://127.0.0.1:8765` après toute modification de `web/app.js`.