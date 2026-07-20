const state = {
  allItems: [],
  language: "all",
  topic: "all",
  query: "",
};

const TOPIC_LABELS = {
  libertad_prensa: "Libertad de Prensa",
  periodismo: "Periodismo",
  migracion: "Migración",
};

const feedList = document.getElementById("feed-list");
const emptyState = document.getElementById("empty-state");
const resultCount = document.getElementById("result-count");
const lastUpdated = document.getElementById("last-updated");
const searchInput = document.getElementById("search");
const langButtons = document.querySelectorAll(".lang-btn");
const topicButtons = document.querySelectorAll(".topic-btn");

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

function matchesFilters(item) {
  if (state.language !== "all" && item.language !== state.language) {
    return false;
  }
  if (state.topic !== "all" && !(item.topics || []).includes(state.topic)) {
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

  if (item.topics && item.topics.includes("migracion")) {
    const topicBadge = document.createElement("span");
    topicBadge.className = "badge badge-migracion";
    topicBadge.textContent = TOPIC_LABELS.migracion;
    meta.appendChild(topicBadge);
  }

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
  const filtered = state.allItems.filter(matchesFilters);
  feedList.innerHTML = "";
  const fragment = document.createDocumentFragment();
  filtered.forEach((item) => fragment.appendChild(renderItem(item)));
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

fetch("./data/feed.json")
  .then((res) => res.json())
  .then((data) => {
    state.allItems = data.items || [];
    lastUpdated.textContent = `Última actualización: ${formatDate(data.generated_at)}`;
    render();
  })
  .catch((err) => {
    lastUpdated.textContent = "No se pudo cargar el feed.";
    console.error(err);
  });
