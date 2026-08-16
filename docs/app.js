const state = {
  allItems: [],
  opportunities: [],
  resources: [],
  language: "all",
  topic: "all",
  kind: "all",
  query: "",
};

const TOPIC_LABELS = {
  libertad_prensa: "Libertad de Prensa",
  periodismo: "Periodismo",
  cpj_americas: "CPJ Américas",
  jsk_stanford: "JSK Stanford",
  medios_exilio: "Medios en el Exilio",
};

// Pestañas que se sirven del catálogo (opportunities.json) en vez del feed de
// noticias: se ordenan por fecha límite, no por fecha de publicación.
const CATALOG_TOPICS = new Set(["oportunidades", "recursos"]);

const KIND_LABELS = {
  empleo: "Empleo",
  beca: "Beca",
  fondo: "Fondo",
  directorio: "Directorio",
  guia: "Guía",
  toolkit: "Kit",
  centro: "Centro de recursos",
};

const SECTION_NOTES = {
  oportunidades:
    "Convocatorias de empleo, becas y fondos. Las de GFMD entran automáticamente; " +
    "el resto es un catálogo revisado a mano, porque esos sitios no publican RSS. " +
    "Confirmá siempre la fecha límite en la convocatoria original antes de postular.",
  recursos:
    "Guías, kits y centros de recursos para periodistas. No caducan: se revisan " +
    "periódicamente para verificar que los enlaces sigan vivos.",
};

const feedList = document.getElementById("feed-list");
const emptyState = document.getElementById("empty-state");
const resultCount = document.getElementById("result-count");
const sectionNote = document.getElementById("section-note");
const lastUpdated = document.getElementById("last-updated");
const searchInput = document.getElementById("search");
const kindFilter = document.getElementById("kind-filter");
const langButtons = document.querySelectorAll(".lang-btn");
const topicButtons = document.querySelectorAll(".topic-btn");
const kindButtons = document.querySelectorAll(".kind-btn");

function stripDiacritics(text) {
  return text.normalize("NFKD").replace(/[̀-ͯ]/g, "");
}

function normalize(text) {
  return stripDiacritics((text || "").toLowerCase());
}

function formatDate(iso) {
  try {
    return new Date(iso).toLocaleString("es-419", {
      dateStyle: "medium",
      timeStyle: "short",
    });
  } catch (e) {
    return iso;
  }
}

function formatDeadline(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("es-419", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

// El estado se calcula en el navegador y no en el script de Python: el
// workflow corre dos veces al día, así que una fecha calculada al generar el
// JSON quedaría desfasada durante horas justo el día en que vence.
function deadlineStatus(entry) {
  if (!entry.deadline) {
    // Sin fecha no significa lo mismo en los dos casos: una entrada curada es
    // un portal que sigue ahí todo el año, mientras que una convocatoria de
    // GFMD sí tiene cierre — solo que no lo declara en un formato legible.
    return entry.origin === "rss"
      ? { key: "sinfecha", label: "Fecha en la convocatoria", days: null }
      : { key: "permanente", label: "Permanente", days: null };
  }
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const [y, m, d] = entry.deadline.split("-").map(Number);
  const days = Math.round((new Date(y, m - 1, d) - today) / 86400000);

  if (days < 0) return { key: "cerrada", label: "Cerrada", days };
  if (days === 0) return { key: "urgente", label: "Cierra hoy", days };
  if (days === 1) return { key: "urgente", label: "Cierra mañana", days };
  if (days <= 14) return { key: "urgente", label: `Cierra en ${days} días`, days };
  return { key: "abierta", label: `Cierra en ${days} días`, days };
}

const STATUS_ORDER = { urgente: 0, abierta: 1, sinfecha: 2, permanente: 3, cerrada: 4 };

function compareEntries(a, b) {
  const sa = deadlineStatus(a);
  const sb = deadlineStatus(b);
  if (STATUS_ORDER[sa.key] !== STATUS_ORDER[sb.key]) {
    return STATUS_ORDER[sa.key] - STATUS_ORDER[sb.key];
  }
  // Con fecha: la más próxima primero. Las cerradas, la más reciente primero.
  if (sa.days !== null && sb.days !== null) {
    return sa.key === "cerrada" ? sb.days - sa.days : sa.days - sb.days;
  }
  // Permanentes: primero las que llegaron por RSS (son novedad), luego el
  // catálogo curado en el orden en que está escrito.
  if (a.published && b.published) return b.published.localeCompare(a.published);
  if (a.published) return -1;
  if (b.published) return 1;
  return 0;
}

function matchesCatalogFilters(entry) {
  if (state.language !== "all" && entry.language !== state.language) {
    return false;
  }
  if (state.topic === "oportunidades" && state.kind !== "all" && entry.kind !== state.kind) {
    return false;
  }
  if (!state.query) {
    return true;
  }
  const haystack = normalize(
    `${entry.name} ${entry.org || ""} ${entry.summary || ""} ${entry.region || ""} ${entry.deadline_note || ""}`
  );
  return haystack.includes(state.query);
}

function renderCatalogEntry(entry) {
  const card = document.createElement("article");
  card.className = "card card-catalog";

  const title = document.createElement("a");
  title.href = entry.url;
  title.target = "_blank";
  title.rel = "noopener";
  title.className = "card-title";
  title.textContent = entry.org ? `${entry.org} — ${entry.name}` : entry.name;
  card.appendChild(title);

  const meta = document.createElement("div");
  meta.className = "card-meta";

  if (entry.kind && KIND_LABELS[entry.kind]) {
    const kindBadge = document.createElement("span");
    kindBadge.className = `badge badge-kind badge-kind-${entry.kind}`;
    kindBadge.textContent = KIND_LABELS[entry.kind];
    meta.appendChild(kindBadge);
  }

  if (state.topic === "oportunidades") {
    const status = deadlineStatus(entry);
    const statusBadge = document.createElement("span");
    statusBadge.className = `badge badge-status badge-status-${status.key}`;
    statusBadge.textContent = status.label;
    meta.appendChild(statusBadge);
  }

  const bits = [];
  if (entry.region) bits.push(entry.region);
  if (entry.deadline) bits.push(`Fecha límite: ${formatDeadline(entry.deadline)}`);
  if (bits.length) meta.appendChild(document.createTextNode(` ${bits.join(" · ")}`));
  card.appendChild(meta);

  if (entry.summary) {
    const summary = document.createElement("p");
    summary.className = "card-summary";
    summary.textContent = entry.summary;
    card.appendChild(summary);
  }

  const footnotes = [];
  if (entry.deadline_note) footnotes.push(entry.deadline_note);
  if (entry.origin === "rss") footnotes.push("Detectada automáticamente vía GFMD");
  if (footnotes.length) {
    const note = document.createElement("p");
    note.className = "card-note";
    note.textContent = footnotes.join(" · ");
    card.appendChild(note);
  }

  if (entry.url_es) {
    const es = document.createElement("a");
    es.href = entry.url_es;
    es.target = "_blank";
    es.rel = "noopener";
    es.className = "card-alt-link";
    es.textContent = "Ver en español →";
    card.appendChild(es);
  }

  return card;
}

// Los medios en el exilio no entran a "Todos": son cobertura de un medio, no un
// reporte de una organización de libertad de prensa, y su filtro por palabras
// clave deja pasar algún falso positivo. Viven solo en su propia pestaña.
const OWN_TAB_ONLY = new Set(["medios_exilio"]);

function matchesFilters(item) {
  if (state.language !== "all" && item.language !== state.language) {
    return false;
  }
  if (state.topic === "all") {
    if ((item.topics || []).some((t) => OWN_TAB_ONLY.has(t))) return false;
  } else if (!(item.topics || []).includes(state.topic)) {
    return false;
  }
  if (!state.query) {
    return true;
  }
  const haystack = normalize(`${item.title} ${item.summary} ${item.source}`);
  return haystack.includes(state.query);
}

function renderItem(item) {
  const card = document.createElement("article");
  card.className = "card";

  const title = document.createElement("a");
  title.href = item.link;
  title.target = "_blank";
  title.rel = "noopener";
  title.className = "card-title";
  title.textContent = item.title;
  card.appendChild(title);

  const meta = document.createElement("div");
  meta.className = "card-meta";
  const badge = document.createElement("span");
  badge.className = `badge badge-${item.language}`;
  badge.textContent = item.language.toUpperCase();
  meta.appendChild(badge);

  meta.appendChild(document.createTextNode(` ${item.source} · ${formatDate(item.published)}`));
  card.appendChild(meta);

  if (item.summary) {
    const summary = document.createElement("p");
    summary.className = "card-summary";
    summary.textContent = item.summary;
    card.appendChild(summary);
  }

  if (item.also_reported_by && item.also_reported_by.length > 0) {
    const also = document.createElement("p");
    also.className = "also-reported";
    const names = item.also_reported_by.map((r) => r.source).join(", ");
    also.textContent = `También reportado por: ${names}`;
    card.appendChild(also);
  }

  return card;
}

function render() {
  const isCatalog = CATALOG_TOPICS.has(state.topic);
  kindFilter.hidden = state.topic !== "oportunidades";
  sectionNote.hidden = !isCatalog;
  if (isCatalog) sectionNote.textContent = SECTION_NOTES[state.topic];

  let filtered;
  let renderOne;
  if (isCatalog) {
    const source = state.topic === "oportunidades" ? state.opportunities : state.resources;
    filtered = source.filter(matchesCatalogFilters);
    if (state.topic === "oportunidades") filtered = filtered.slice().sort(compareEntries);
    renderOne = renderCatalogEntry;
  } else {
    filtered = state.allItems.filter(matchesFilters);
    renderOne = renderItem;
  }

  feedList.innerHTML = "";
  const fragment = document.createDocumentFragment();
  filtered.forEach((entry) => fragment.appendChild(renderOne(entry)));
  feedList.appendChild(fragment);

  resultCount.textContent = `${filtered.length} resultado${filtered.length === 1 ? "" : "s"}`;
  emptyState.hidden = filtered.length !== 0;
}

searchInput.addEventListener("input", (e) => {
  state.query = normalize(e.target.value.trim());
  render();
});

langButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    langButtons.forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    state.language = btn.dataset.lang;
    render();
  });
});

topicButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    topicButtons.forEach((b) => {
      b.classList.remove("active");
      b.setAttribute("aria-selected", "false");
    });
    btn.classList.add("active");
    btn.setAttribute("aria-selected", "true");
    state.topic = btn.dataset.topic;
    render();
  });
});

kindButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    kindButtons.forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    state.kind = btn.dataset.kind;
    render();
  });
});

Promise.all([
  fetch("./data/feed.json").then((res) => res.json()),
  // El catálogo se agregó después que el feed; si un despliegue viejo todavía
  // no tiene el archivo, el sitio sigue funcionando sin las dos pestañas nuevas.
  fetch("./data/opportunities.json")
    .then((res) => (res.ok ? res.json() : null))
    .catch(() => null),
])
  .then(([feed, catalog]) => {
    state.allItems = feed.items || [];
    state.opportunities = (catalog && catalog.opportunities) || [];
    state.resources = (catalog && catalog.resources) || [];
    lastUpdated.textContent = `Última actualización: ${formatDate(feed.generated_at)}`;
    render();
  })
  .catch((err) => {
    lastUpdated.textContent = "No se pudo cargar el feed.";
    console.error(err);
  });
