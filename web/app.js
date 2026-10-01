"use strict";

const state = {
  items: [],
  themes: new Set(),
  solutions: new Set(),
  config: {},
  busy: false,
};

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
};
const normalise = (s) =>
  (s || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();

const iso = (d) => d.toISOString().slice(0, 10);
const daysAgo = (n) => iso(new Date(Date.now() - n * 86400000));

/* ------------------------------------------------------------------ réseau */
async function api(path, options) {
  const response = await fetch(path, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

async function loadConfig() {
  state.config = await api("/api/config");
  const last = state.config.last_week || [daysAgo(7), daysAgo(1)];
  $("#debut").value = last[0];
  $("#fin").value = last[1];
  $("#preset").value = "7";
  $("#config-line").textContent =
    `Chambres suivies : ${(state.config.chambers || []).join(", ")} · ` +
    `source : ${
      state.config.source === "dila"
        ? "données ouvertes DILA (gratuit)"
        : `PISTE${state.config.piste_configured ? "" : " (identifiants absents)"}`
    } · ` +
    `synthèse IA : ${state.config.llm === "none" ? "désactivée (extraits seuls)" : state.config.llm_model}`;
}

async function load() {
  const debut = $("#debut").value;
  const fin = $("#fin").value;
  const qs = new URLSearchParams();
  if (debut && fin) {
    qs.set("debut", debut);
    qs.set("fin", fin);
  }
  try {
    const data = await api(`/api/decisions?${qs}`);
    state.items = data.arrets || [];
    state.busy = !!data.busy;
    if (data.last_error) banner(data.last_error, "err");
    render();
  } catch (err) {
    banner(err.message, "err");
  }
}

/* -------------------------------------------------------------- rendu global */
function banner(message, kind) {
  const node = $("#banner");
  if (!message) {
    node.classList.add("hidden");
    return;
  }
  node.textContent = message;
  node.className = `banner ${kind || ""}`;
}

function render() {
  renderStats();
  renderThemeBar();
  renderSolutionFilter();
  renderList();
}

function renderStats() {
  const items = state.items;
  const bulletin = items.filter((i) => i.meta.au_bulletin).length;
  const cassation = items.filter((i) => (i.meta.solution || "").toLowerCase().includes("casse")).length;
  const distinct = new Set();
  items.forEach((i) => (i.themes || []).forEach((t) => distinct.add(t.code)));
  $("#stat-total").textContent = items.length;
  $("#stat-bulletin").textContent = bulletin;
  $("#stat-cassation").textContent = cassation;
  $("#stat-themes").textContent = distinct.size;
}

function renderThemeBar() {
  const counts = new Map();
  state.items.forEach((item) => {
    (item.themes || []).forEach((theme) => {
      const entry = counts.get(theme.code) || { label: theme.label, icon: theme.icon, n: 0 };
      entry.n += 1;
      counts.set(theme.code, entry);
    });
  });
  const bar = $("#chips");
  bar.textContent = "";
  const sorted = [...counts.entries()].sort((a, b) => b[1].n - a[1].n || a[1].label.localeCompare(b[1].label));
  sorted.forEach(([code, entry]) => {
    const chip = el("span", "chip");
    chip.append(`${entry.icon} ${entry.label}`);
    const count = el("span", "count", String(entry.n));
    chip.append(count);
    if (state.themes.has(code)) chip.classList.add("on");
    chip.title = "Filtrer sur ce thème";
    chip.onclick = () => {
      if (state.themes.has(code)) state.themes.delete(code);
      else state.themes.add(code);
      renderList();
      renderThemeBar();
    };
    bar.append(chip);
  });
}

function renderSolutionFilter() {
  const select = $("#solution");
  const solutions = new Set(state.items.map((i) => i.meta.solution).filter(Boolean));
  const current = select.value;
  select.textContent = "";
  select.append(el("option", null, "Toutes les solutions"));
  select.firstChild.value = "";
  [...solutions].sort().forEach((value) => {
    const label = state.items.find((i) => i.meta.solution === value).meta.solution_label || value;
    const option = el("option", null, label);
    option.value = value;
    select.append(option);
  });
  select.value = solutions.has(current) ? current : "";
}

function matches(item) {
  if (state.themes.size) {
    const codes = new Set((item.themes || []).map((t) => t.code));
    const any = [...state.themes].some((code) => codes.has(code));
    if (!any) return false;
  }
  if ($("#only-bulletin").checked && !item.meta.au_bulletin) return false;
  if ($("#only-particulier").checked && !item.meta.particulier_interet) return false;
  const solution = $("#solution").value;
  if (solution && item.meta.solution !== solution) return false;

  const needle = normalise($("#search").value.trim());
  if (!needle) return true;
  const haystack = normalise(
    [
      item.meta.number,
      item.meta.ecli,
      item.meta.summary,
      item.meta.solution_label,
      (item.meta.themes_officiels || []).join(" "),
      (item.themes || []).map((t) => t.label).join(" "),
      (item.attendu || []).join(" "),
      (item.motifs || []).join(" "),
      (item.portee || []).join(" "),
      (item.moyens || []).join(" "),
      (item.textes_appliques || []).join(" "),
      item.text,
    ].join(" ")
  );
  return needle.split(/\s+/).every((token) => haystack.includes(token));
}

function sortItems(items) {
  const mode = $("#sort").value;
  const byDate = (a, b) => (a.meta.decision_date || "").localeCompare(b.meta.decision_date || "");
  const copy = [...items];
  if (mode === "date-asc") return copy.sort(byDate);
  if (mode === "bulletin")
    return copy.sort((a, b) => (b.meta.au_bulletin ? 1 : 0) - (a.meta.au_bulletin ? 1 : 0) || byDate(b, a));
  if (mode === "theme")
    return copy.sort((a, b) => {
      const la = (a.themes[0] || {}).label || "";
      const lb = (b.themes[0] || {}).label || "";
      return la.localeCompare(lb) || byDate(b, a);
    });
  return copy.sort((a, b) => byDate(b, a));
}

function renderList() {
  const list = $("#list");
  list.textContent = "";
  const items = sortItems(state.items.filter(matches));
  if (!items.length) {
    const empty = el("div", "empty");
    empty.textContent = state.items.length
      ? "Aucun arrêt ne correspond aux filtres."
      : state.config.source === "piste"
        ? "Aucun arrêt enregistré. Cliquez sur « Actualiser » — des identifiants PISTE sont requis."
        : "Aucun arrêt enregistré. Cliquez sur « Actualiser » pour télécharger les données ouvertes de la Cour.";
    list.append(empty);
    return;
  }
  const template = $("#tpl-card");
  items.forEach((item) => list.append(buildCard(item, template)));
}

/* -------------------------------------------------------------- carte arrêt */
/* `root`限 la recherche à la carte courante : sans cela, `querySelector`
   renvoie la première carte du document et les résumés s'empilent sur la
   première fiche au lieu de se répartir. */
/* `root` limite la recherche à la carte courante : sans cela, `querySelector`
   renvoie la première carte du document et les résumés s'empilent sur la
   première fiche au lieu de se répartir. */
function fillList(root, selector, lines) {
  const list = root.querySelector(selector);
  if (!list) return;
  list.textContent = "";
  (lines || []).forEach((line) => list.append(el("li", null, String(line))));
}

function buildCard(item, template) {
  const card = template.content.firstElementChild.cloneNode(true);
  const meta = item.meta;
  if (meta.au_bulletin) card.classList.add("bulletin");

  card.querySelector(".date").textContent = meta.decision_date || "";
  card.querySelector(".num").textContent = `n° ${meta.number || "—"}`;
  card.querySelector(".sol").textContent = meta.solution_label || meta.solution || "";

  const badges = card.querySelector(".badges");
  if (meta.au_bulletin) {
    const badge = el("span", "badge b");
    badge.textContent = meta.bulletin_numero
      ? `📌 Bulletin ${meta.bulletin_numero}`
      : "📌 Publié au bulletin (B)";
    badges.append(badge);
  }
  if (meta.au_rapport) badges.append(el("span", "badge r", "📖 Rapport (R)"));
  (meta.publication_labels || []).forEach((label) => {
    if (/communiqué|recueil|tradu/i.test(label)) badges.append(el("span", "badge", label));
  });
  if ((meta.solution || "").toLowerCase().includes("casse"))
    badges.append(el("span", "badge cassation", "Casse et annule"));
  if (meta.particulier_interet) badges.append(el("span", "badge star", "⭐ Intérêt particulier"));
  if (meta.extrait_partiel) badges.append(el("span", "badge", "⚠️ Publié par extraits"));

  const official = card.querySelector(".official");
  if (meta.summary) {
    official.append(el("b", null, "Sommaire de la Cour : "));
    official.append(document.createTextNode(meta.summary));
  }
  const officialThemes = meta.themes_officiels || [];
  if (officialThemes.length) {
    official.append(el("br"));
    official.append(el("span", null, `Matières : ${officialThemes.slice(0, 6).join(", ")}`));
  }

  const chips = card.querySelector(".chips.small");
  (item.themes || []).forEach((theme) => {
    const chip = el("span", "chip");
    chip.append(`${theme.icon} ${theme.label}`);
    if (theme.evidence && theme.evidence.length) chip.title = theme.note || "";
    chips.append(chip);
  });

  fillList(card, ".attendu", item.attendu);
  fillList(card, ".solution", item.solution_texte);
  fillList(card, ".motifs", item.motifs);
  fillList(card, ".portee", item.portee);
  fillList(card, ".moyens", item.moyens);
  fillList(card, ".textes", item.textes_appliques);

  const evidences = card.querySelector(".evidences");
  const evi = card.querySelector(".evi");
  const withEvidence = (item.themes || []).filter((t) => (t.evidence || []).length);
  if (withEvidence.length) {
    withEvidence.forEach((theme) => {
      const wrap = el("div", "evi-item");
      wrap.append(el("b", null, `${theme.icon} ${theme.label} `));
      wrap.append(el("span", "why", theme.note || ""));
      theme.evidence.forEach((quote) => {
        const block = el("blockquote", null, quote);
        wrap.append(block);
      });
      evi.append(wrap);
    });
    evidences.classList.remove("hidden");
  }

  const citations = card.querySelector(".citations");
  const cit = card.querySelector(".cit");
  const cited = (item.citations || []).filter((c) => c.quote);
  if (cited.length) {
    cited.forEach((entry) => {
      const wrap = el("div");
      wrap.append(el("span", "zone", `${entry.zone || "texte"} · ${entry.verified ? "citation vérifiée" : "non retrouvée"}`));
      wrap.append(el("blockquote", null, entry.quote));
      cit.append(wrap);
    });
    citations.classList.remove("hidden");
  }

  card.querySelector(".fulltext pre").textContent = item.text || "(texte indisponible)";

  const foot = card.querySelector(".card-foot");
  const sources = [
    meta.source === "dila" ? "Légifrance" : "Cour de cassation",
    meta.source === "dila" && meta.url_legifrance ? "DILA" : null,
  ].filter(Boolean);
  if (meta.url) {
    const link = el("a", null, `${sources[0]} ↗`);
    link.href = meta.url;
    link.target = "_blank";
    link.rel = "noopener";
    foot.append(link);
  }
  if (meta.url_legifrance && meta.source !== "dila") {
    const link = el("a", null, "Légifrance ↗");
    link.href = meta.url_legifrance;
    link.target = "_blank";
    link.rel = "noopener";
    foot.append(link);
  }
  foot.append(el("span", null, `ECLI : ${meta.ecli || "—"}`));
  if (item.fiabilite) foot.append(el("span", "fiab", item.fiabilite));

  const toggle = card.querySelector(".toggle");
  const body = card.querySelector(".body");
  toggle.onclick = () => {
    body.classList.toggle("hidden");
    toggle.textContent = body.classList.contains("hidden") ? "Détail" : "Replier";
  };

  card.dataset.search = normalise(
    [
      meta.number,
      meta.summary,
      (item.attendu || []).join(" "),
      (item.motifs || []).join(" "),
      item.text,
    ].join(" ")
  );
  return card;
}

/* ------------------------------------------------------------------ exports */
function download(name, content, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const link = el("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

function slug(items) {
  const dates = items.map((i) => i.meta.decision_date).filter(Boolean).sort();
  return `${dates[0] || "debut"}_${dates[dates.length - 1] || "fin"}`;
}

function toMarkdown(items) {
  const lines = [
    `# Arrêts de la chambre criminelle — ${slug(items)}`,
    "",
    `Généré le ${new Date().toLocaleString("fr-FR")} · ${items.length} arrêt(s), ` +
      `${items.filter((i) => i.meta.au_bulletin).length} publié(s) au bulletin.`,
    "",
    "> Synthèses issues du texte de la Cour (extraits vérifiés). La citation de l'arrêt prévaut.",
    "",
  ];
  items.forEach((item) => {
    const meta = item.meta;
    lines.push(`## ${meta.decision_date} — pourvoi n° ${meta.number}`, "");
    if (meta.au_bulletin) lines.push("**Publié au bulletin (B)**", "");
    if (meta.ecli) lines.push(`- ECLI : \`${meta.ecli}\``);
    lines.push(`- Solution : ${meta.solution_label || meta.solution || "—"}`);
    const themes = (item.themes || []).map((t) => `${t.icon} ${t.label}`).join(" · ");
    if (themes) lines.push(`- Thèmes : ${themes}`);
    if (meta.url) lines.push(`- Source : <${meta.url}>`);
    lines.push("", "### L'attendu de la Cour", "");
    (item.attendu || []).forEach((t) => lines.push(`- ${t}`));
    lines.push("", "### La solution", "");
    (item.solution_texte || []).forEach((t) => lines.push(`- ${t}`));
    if ((item.motifs || []).length) {
      lines.push("", "### Les motifs", "");
      item.motifs.forEach((t) => lines.push(`- ${t}`));
    }
    if ((item.textes_appliques || []).length) {
      lines.push("", "### Textes appliqués", "");
      item.textes_appliques.slice(0, 12).forEach((t) => lines.push(`- ${t}`));
    }
    lines.push("", `_${item.fiabilite || ""}_`, "", "---", "");
  });
  return lines.join("\n");
}

/* ------------------------------------------------------------------ actions */
async function update() {
  const button = $("#btn-update");
  if (state.busy) return;
  button.disabled = true;
  banner(
    state.config.source === "piste"
      ? "Actualisation en cours : interrogation de l'API Judilibre…"
      : "Actualisation en cours : téléchargement des données ouvertes de la Cour…",
    ""
  );
  try {
    await api("/api/update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ debut: $("#debut").value, fin: $("#fin").value }),
    });
    poll();
  } catch (err) {
    banner(err.message, "err");
    button.disabled = false;
  }
}

function poll(attempt = 0) {
  setTimeout(async () => {
    const data = await api("/api/decisions").catch(() => null);
    if (!data) return;
    if (data.busy && attempt < 90) {
      banner("Actualisation en cours…", "");
      return poll(attempt + 1);
    }
    state.busy = false;
    $("#btn-update").disabled = false;
    if (data.last_error) banner(data.last_error, "err");
    else banner("Actualisation terminée.", "ok");
    await load();
    setTimeout(() => banner(""), 6000);
  }, 1200);
}

function applyPreset(value) {
  const today = new Date();
  if (value === "tout") {
    $("#debut").value = "";
    $("#fin").value = "";
  } else if (value === "semaine") {
    const end = new Date(Date.now() - ((today.getDay() + 6) % 7 || 7) * 86400000);
    const start = new Date(end.getTime() - 6 * 86400000);
    $("#debut").value = iso(start);
    $("#fin").value = iso(end);
  } else {
    const n = parseInt(value, 10);
    $("#debut").value = daysAgo(n);
    $("#fin").value = n === 7 ? daysAgo(1) : iso(today);
  }
  load();
}

/* ---------------------------------------------------------------- démarrage */
function init() {
  loadConfig()
    .then(load)
    .catch((err) => banner(err.message, "err"));
  $("#btn-update").onclick = update;
  $("#preset").onchange = (event) => applyPreset(event.target.value);
  $("#debut").onchange = load;
  $("#fin").onchange = load;
  $("#search").oninput = renderList;
  $("#solution").onchange = renderList;
  $("#only-bulletin").onchange = renderList;
  $("#only-particulier").onchange = renderList;
  $("#sort").onchange = renderList;
  $("#btn-export-md").onclick = () => {
    const items = sortItems(state.items.filter(matches));
    download(`veille_criminelle_${slug(items)}.md`, toMarkdown(items), "text/markdown;charset=utf-8");
  };
  $("#btn-export-json").onclick = () => {
    const items = sortItems(state.items.filter(matches));
    download(`veille_criminelle_${slug(items)}.json`, JSON.stringify(items, null, 2), "application/json");
  };
  setInterval(() => {
    if (!state.busy) load();
  }, 30000);
}

document.addEventListener("DOMContentLoaded", init);
