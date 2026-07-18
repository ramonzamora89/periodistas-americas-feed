# Ataques a Periodistas en las Américas

Feed agregado, en español e inglés, de ataques contra periodistas en toda la región de las Américas. Combina fuentes RSS de organizaciones de libertad de prensa y 20 Google Alerts, y publica una sola página estática vía GitHub Pages que se actualiza sola con GitHub Actions.

Sitio: `https://<usuario>.github.io/<repo>/` (se llena tras el primer deploy).

## Cómo funciona

- `config/sources.yaml` — lista de fuentes RSS/Atom con metadata (idioma, país, prioridad).
- `scripts/fetch_feeds.py` — descarga todas las fuentes activas, normaliza cada entrada, elimina duplicados (exactos por link y difusos por título+fecha cuando dos fuentes cubren el mismo caso) y escribe `docs/data/feed.json` + `docs/data/status.json`.
- `docs/` — sitio estático (HTML/CSS/JS sin build step) que lee `data/feed.json` y renderiza la lista con buscador y filtro de idioma. Es la raíz que sirve GitHub Pages.
- `.github/workflows/update-feed.yml` — corre el fetch dos veces al día (cron `17 9,21 * * *` UTC), y en cada push a `scripts/` o `config/`; comitea `docs/data/*.json` si hay cambios.

## Agregar una fuente

Agregar una entrada en `config/sources.yaml` con `active: true`. Campos: `id`, `name`, `url` (RSS/Atom), `language` (`en`/`es`), `country` (o `null` si es regional), `priority` (1=más autorizada, para desempatar duplicados — 1=CPJ, 2=RSF, 3=orgs regionales, 4=Google Alerts).

## Google Alerts

Las 20 alertas (10 en inglés, 10 en español) ya están creadas en la cuenta de Google del usuario y activas en `config/sources.yaml` (prioridad 4, `alert_en_*` / `alert_es_*`), configuradas con **Sources: Automatic**, **How many: All results**, **Deliver to: RSS feed**:

**Inglés:**
1. `"journalist killed" Latin America`
2. `"journalist murdered" OR "reporter killed" Latin America`
3. `"journalist attacked" OR "journalist assaulted" Latin America`
4. `"journalist threatened" OR "journalist harassed" Latin America`
5. `"journalist detained" OR "journalist arrested" Latin America`
6. `"journalist kidnapped" Latin America`
7. `"press freedom" attack Latin America`
8. `journalist censored OR "media censorship" Latin America`
9. `journalist "legal harassment" OR SLAPP journalist Latin America`
10. `journalist exiled OR "forced into exile" journalist Latin America`

**Español:**
1. `"periodista asesinado" OR "periodista asesinada"`
2. `"periodista amenazado" OR "periodista amenazada"`
3. `"periodista agredido" OR "periodista atacado"`
4. `"periodista detenido" OR "periodista detenida"`
5. `"periodista secuestrado" OR "periodista secuestrada"`
6. `"periodista desaparecido"`
7. `censura periodista OR "censura a periodistas"`
8. `"periodista demandado" OR "demanda contra periodista"`
9. `"periodista exiliado" OR periodista exilio`
10. `"reportero agredido" OR "reportera agredida"`

Para agregar/editar alertas: ir a [google.com/alerts](https://www.google.com/alerts) → "My alerts". La URL del feed RSS no aparece en la pantalla de creación — hay que hacer clic en el ícono RSS junto a la alerta para copiarla, y pegarla en `config/sources.yaml`.

## Fuentes sin RSS (revisión manual)

**NoNosCallarán** es un colectivo guatemalteco sin sitio propio, activo solo en X: [@NoNosCallaranGT](https://x.com/NoNosCallaranGT). No se integra al pipeline automático — revisar manualmente.

## Desarrollo local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt
python scripts/fetch_feeds.py

cd docs && python3 -m http.server 8000
# abrir http://localhost:8000/ — no abrir como file://, rompe el fetch de data/feed.json
```

## Mantenimiento

GitHub pausa automáticamente los workflows programados (`schedule`) después de 60 días sin ningún commit en el repo. Si el feed se ve desactualizado tras una inactividad larga, correr `gh workflow run update-feed.yml` una vez reactiva el schedule.
