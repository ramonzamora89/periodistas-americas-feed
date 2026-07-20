# El Feed: Libertad de Prensa en las Américas

Feed agregado, en español e inglés, sobre libertad de prensa, periodismo y migración en toda la región de las Américas. Combina fuentes RSS de organizaciones de libertad de prensa, gremios/academia de periodismo y 20 Google Alerts, y publica una sola página estática vía GitHub Pages que se actualiza sola con GitHub Actions.

Sitio: `https://<usuario>.github.io/<repo>/` (se llena tras el primer deploy).

## Cómo funciona

- `config/sources.yaml` — lista de fuentes RSS/Atom con metadata (idioma, país, prioridad, categoría).
- `scripts/fetch_feeds.py` — descarga todas las fuentes activas, normaliza cada entrada, elimina duplicados (exactos por link y difusos por título+fecha cuando dos fuentes cubren el mismo caso), clasifica cada item por tema y escribe `docs/data/feed.json` + `docs/data/status.json`.
- `docs/` — sitio estático (HTML/CSS/JS sin build step) que lee `data/feed.json` y renderiza la lista con buscador, pestañas de tema y filtro de idioma. Es la raíz que sirve GitHub Pages.
- `.github/workflows/update-feed.yml` — corre el fetch dos veces al día (cron `17 9,21 * * *` UTC), y en cada push a `scripts/` o `config/`; comitea `docs/data/*.json` si hay cambios.

## Pestañas de tema

El sitio filtra por tres pestañas (además de "Todos"):

- **Libertad de Prensa** — ataques, censura, detenciones, informes de organismos especializados. Viene de la `category: libertad_prensa` de la fuente (CPJ, RSF, Artículo 19, Google Alerts, U.S. Press Freedom Tracker, Freedom of the Press Foundation, Free Press Action, IPYS, SNTP Venezuela, etc.).
- **Periodismo** — industria/oficio periodístico: tendencias, investigación académica, gremios (`category: periodismo`, ej. LatAm Journalism Review, Reuters Institute).
- **Migración** — no es una `category` de fuente, sino una clasificación por palabras clave (`MIGRATION_KEYWORDS` en `scripts/fetch_feeds.py`) aplicada al título+resumen de **cualquier** item, sin importar su categoría primaria. Así un caso de censura a un periodista que cubre migración aparece tanto en Libertad de Prensa como en Migración.

## Agregar una fuente

Agregar una entrada en `config/sources.yaml` con `active: true`. Campos: `id`, `name`, `url` (RSS/Atom), `language` (`en`/`es`), `country` (o `null` si es regional), `priority` (1=más autorizada, para desempatar duplicados — 1=CPJ, 2=RSF, 3=orgs regionales/otras, 4=Google Alerts), `category` (`libertad_prensa` o `periodismo`, pestaña primaria en el sitio).

Si un sitio no publica RSS/Atom (ej. requiere JS, o lo desactivó deliberadamente), no se puede meter al pipeline automático — se agrega como enlace de revisión manual en el footer de `docs/index.html`, igual que NoNosCallarán, SIP/IAPA, IPI, NPPA y la CIDH.

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

Listadas en el footer de `docs/index.html`:

- **NoNosCallarán** — colectivo guatemalteco sin sitio propio, activo solo en X: [@NoNosCallaranGT](https://x.com/NoNosCallaranGT).
- **SIP/IAPA** ([en.sipiapa.org](https://en.sipiapa.org)) — sin RSS detectado (CMS propio, sin autodiscovery ni rutas estándar).
- **IPI** ([ipi.media](https://ipi.media)) — WordPress con el feed nativo desactivado (`/feed/` y `?feed=rss2` redirigen al home).
- **NPPA** ([nppa.org](https://nppa.org)) — sitio Next.js, sin ruta de feed.
- **CIDH – Relatoría Especial para la Libertad de Expresión** ([oas.org/es/cidh/expresion](https://www.oas.org/es/cidh/expresion/index.asp)) — sitio institucional sin RSS.

Ninguna se integra al pipeline automático — revisar manualmente.

## Identidad visual

`logos/` tiene los PNG originales (perfil circular, logo cuadrado, banner ancho). `docs/assets/` tiene copias redimensionadas/comprimidas con `sips`+`pngquant` para el sitio: `favicon.png` (128×128, ícono de pestaña) y `banner.png` (1600×533, header). El logo cuadrado no se usa en el sitio; queda disponible en `logos/` para redes sociales u otros usos.

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
