// Test hors-ligne de web/app.js : on charge le VRAI index.html et le VRAI
// app.js dans un DOM minimal (linkedom), avec un `fetch` qui interroge le
// serveur local. Ce test reproduit les erreurs d'exécution à l'écran et
// vérifie que chaque fiche reçoit ses propres résumés.
//
//   node /tmp/opencode/test_app.mjs          # serveur attendu sur :8765
//   BASE=http://127.0.0.1:8899 node …        # autre port
//
// Ce n'est pas un substitut à un test dans un vrai navigateur : c'est un garde
//-fou rapide contre les régressions de rendu.
import { readFileSync } from "node:fs";
// `linkedom` n'est pas installé par défaut : le test est ignoré proprement.
let parseHTML = null;
try {
  ({ parseHTML } = await import("linkedom"));
} catch {
  console.log("ignoré : npm install linkedom (non requis par le projet Python)");
  process.exit(0);
}

const ROOT = new URL("../..", import.meta.url).pathname.replace(/\/$/, "");
const BASE = process.env.BASE || "http://127.0.0.1:8765";

const html = readFileSync(`${ROOT}/web/index.html`, "utf8");
const js = readFileSync(`${ROOT}/web/app.js`, "utf8");
const { window, document } = parseHTML(html);

// linkedom expose `value` en lecture seule sur les <input> : on le rend
// inscriptible pour que le harnais se comporte comme un navigateur.
for (const input of document.querySelectorAll("input, select")) {
  const initial = input.value;
  let current = initial;
  Object.defineProperty(input, "value", {
    get: () => current,
    set: (v) => { current = v; },
    configurable: true,
  });
}

const nodeFetch = globalThis.fetch;
const fakeFetch = async (path, options) => {
  const res = await nodeFetch(BASE + path, options);
  return { ok: res.ok, status: res.status, json: async () => res.json() };
};

// On exécute app.js dans la portée réelle du module : les globales (Promise,
// URLSearchParams…) sont alors celles d'un navigateur.
const run = new Function(
  "document", "window", "fetch", "setTimeout", "clearTimeout", "URL", "Blob",
  js + "\n;return { init, state, buildCard, renderList, fillList };",
);

const erreurs = [];
const erreurConsole = console.error;
console.error = (...a) => erreurs.push(a.map(String).join(" "));

let api = null;
try {
  api = run(document, window, fakeFetch, setTimeout, clearTimeout, window.URL, window.Blob);
  api.init();
} catch (err) {
  erreurs.push(`${err.name}: ${err.message}`);
}

await new Promise((r) => setTimeout(r, 2500));
console.error = erreurConsole;

const cartes = document.querySelectorAll("#list .card");
const dansCartes = (sel) => [...document.querySelectorAll(`#list .card ${sel}`)];
const remplis = (nodes) => nodes.filter((n) => n.children.length > 0).length;
const attendus = dansCartes("ul.attendu");
const solutions = dansCartes("ul.solution");
const motifs = dansCartes("ul.motifs");
const moyens = dansCartes("ul.moyens");
const textes = dansCartes("ul.textes");

const verif = [];
const ck = (nom, ok, detail = "") => verif.push({ nom, ok, detail });

const banniere = document.querySelector("#banner")?.textContent || "";
ck("aucun message d'erreur à l'écran", banniere === "", banniere);
ck("aucune erreur console", erreurs.length === 0, erreurs.join(" | "));
ck("des fiches sont rendues", cartes.length > 0, `${cartes.length} fiche(s)`);

if (cartes.length) {
  ck("chaque fiche porte son « attendu »",
    attendus.length === cartes.length && remplis(attendus) === cartes.length,
    `${remplis(attendus)}/${attendus.length}`);
  ck("chaque fiche porte sa solution",
    solutions.length === cartes.length && remplis(solutions) === cartes.length,
    `${remplis(solutions)}/${solutions.length}`);
  ck("chaque fiche porte ses motifs",
    motifs.length === cartes.length && remplis(motifs) === cartes.length,
    `${remplis(motifs)}/${motifs.length}`);
  ck("les « attendus » sont distincts d'une fiche à l'autre",
    new Set(attendus.map((n) => n.children[0]?.textContent?.slice(0, 40))).size >= Math.min(cartes.length, 3),
    `${new Set(attendus.map((n) => n.children[0]?.textContent?.slice(0, 40))).size} premiers extraits distincts`);
  ck("le texte intégral est présent",
    dansCartes(".fulltext pre").every((n) => n.textContent.length > 200));
  ck("chaque fiche a un lien vers la source",
    dansCartes(".card-foot a").length === cartes.length,
    `${dansCartes(".card-foot a").length}/${cartes.length}`);
  ck("les fiches sont dépliables",
    dansCartes(".toggle").every((n) => typeof n.onclick === "function"));
}

ck("les moyens du pourvoi sont remplis", remplis(moyens) > 0, `${remplis(moyens)}/${moyens.length}`);
ck("les textes appliqués sont remplis", remplis(textes) > 0, `${remplis(textes)}/${textes.length}`);
ck("le bandeau annonce la source DILA",
  (document.querySelector("#config-line")?.textContent || "").includes("DILA"),
  document.querySelector("#config-line")?.textContent);
ck("les compteurs sont numériques",
  ["#stat-total", "#stat-bulletin", "#stat-cassation", "#stat-themes"]
    .every((s) => /^\d+$/.test(document.querySelector(s)?.textContent?.trim() || "")),
  ["#stat-total", "#stat-bulletin", "#stat-cassation", "#stat-themes"]
    .map((s) => document.querySelector(s)?.textContent).join(" / "));

let ko = 0;
for (const { nom, ok, detail } of verif) {
  if (!ok) ko++;
  console.log(`${ok ? "ok  " : "FAIL"} ${nom}${detail ? "  — " + detail : ""}`);
}
console.log(`\n${verif.length - ko}/${verif.length} vérifications passées · ${cartes.length} fiche(s) rendue(s)`);
process.exit(ko ? 1 : 0);