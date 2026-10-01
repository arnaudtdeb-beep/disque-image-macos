// Vérifie que les filtres et le repli ne cassent pas le rendu.
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
for (const i of document.querySelectorAll("input, select")) {
  let cur = i.value;
  Object.defineProperty(i, "value", { get: () => cur, set: (v) => { cur = v; }, configurable: true });
}
const nf = globalThis.fetch;
const fakeFetch = async (p, o) => { const r = await nf(BASE + p, o); return { ok: r.ok, status: r.status, json: async () => r.json() }; };
const run = new Function("document","window","fetch","setTimeout","clearTimeout","URL","Blob", js + "\n;return { init, state, renderList, toMarkdown, sortItems, matches };");
const api = run(document, window, fakeFetch, setTimeout, clearTimeout, window.URL, window.Blob);
api.init();
await new Promise((r) => setTimeout(r, 2500));

const nb = () => document.querySelectorAll("#list .card").length;
const verif = [];
const ck = (n, ok, d = "") => verif.push({ n, ok, d });
const base = nb();
ck("des fiches au départ", base > 0, `${base}`);

// filtre « publié au bulletin »
document.querySelector("#only-bulletin").checked = true;
api.renderList();
ck("filtre bulletin : sous-ensemble cohérent", nb() <= base && nb() >= 0, `${nb()}/${base}`);
document.querySelector("#only-bulletin").checked = false;
api.renderList();
ck("filtre bulletin désactivé", nb() === base, `${nb()}`);

// recherche
document.querySelector("#search").value = "douane";
api.renderList();
const apresRecherche = nb();
ck("recherche « douane » filtre", apresRecherche <= base, `${apresRecherche}/${base}`);
document.querySelector("#search").value = "";
api.renderList();
ck("recherche vidée : retour au complet", nb() === base, `${nb()}`);

// recherche sans résultat
document.querySelector("#search").value = "zzzqqq";
api.renderList();
ck("recherche vide : message affiché",
  (document.querySelector("#list .empty")?.textContent || "").includes("Aucun arrêt ne correspond"),
  document.querySelector("#list .empty")?.textContent);
document.querySelector("#search").value = "";
api.renderList();

// période sans données
document.querySelector("#debut").value = "2019-01-01";
document.querySelector("#fin").value = "2019-01-02";
// le harnais n'a pas d'événements : on appelle les gestionnaires directement
document.querySelector("#debut").onchange();
await new Promise((r) => setTimeout(r, 1200));
ck("période sans données : message d'état",
  /Aucun arrêt/.test(document.querySelector("#list .empty")?.textContent || ""),
  document.querySelector("#list .empty")?.textContent?.slice(0, 80));

// retour à une période réellement peuplée avant de tester l'export
document.querySelector("#debut").value = "2026-01-01";
document.querySelector("#fin").value = "2026-12-31";
document.querySelector("#debut").onchange();
await new Promise((r) => setTimeout(r, 1200));
ck("recharge après changement de période", nb() > 0, `${nb()} fiches`);

// export Markdown
const md = api.toMarkdown(api.state.items);
ck("export Markdown non vide", md.length > 200 && md.includes("L'attendu de la Cour"), `${md.length} caractères`);

let ko = 0;
for (const { n, ok, d } of verif) { if (!ok) ko++; console.log(`${ok ? "ok  " : "FAIL"} ${n}${d ? "  — " + d : ""}`); }
console.log(`\n${verif.length - ko}/${verif.length} vérifications passées`);
process.exit(ko ? 1 : 0);
