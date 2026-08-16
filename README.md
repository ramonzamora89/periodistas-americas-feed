# El Feed: Libertad de Prensa en las Américas

Feed agregado, en español e inglés, sobre libertad de prensa y periodismo en toda la región de las Américas. Combina fuentes RSS de organizaciones de libertad de prensa, gremios/academia de periodismo y 20 Google Alerts, y publica una sola página estática vía GitHub Pages que se actualiza sola con GitHub Actions.

Sitio: `https://<usuario>.github.io/<repo>/` (se llena tras el primer deploy).

## Cómo funciona

- `config/sources.yaml` — lista de fuentes RSS/Atom con metadata (idioma, país, prioridad, categoría).
- `config/opportunities.yaml` — catálogo curado a mano de convocatorias y recursos, para los sitios que no publican RSS.
- `scripts/fetch_feeds.py` — descarga todas las fuentes activas, normaliza cada entrada, elimina duplicados (exactos por link y difusos por título+fecha cuando dos fuentes cubren el mismo caso), clasifica cada item por tema y escribe `docs/data/feed.json`, `docs/data/opportunities.json` y `docs/data/status.json`.
- `docs/` — sitio estático (HTML/CSS/JS sin build step) que lee esos JSON y renderiza la lista con buscador, pestañas de tema y filtro de idioma. Es la raíz que sirve GitHub Pages.
- `.github/workflows/update-feed.yml` — corre el fetch dos veces al día (cron `17 9,21 * * *` UTC), y en cada push a `scripts/` o `config/`; comitea `docs/data/*.json` si hay cambios.

## Pestañas de tema

Cinco pestañas se sirven del feed de noticias (además de "Todos"). Las dos primeras agrupan por tema y las tres últimas por medio. El menú va en dos filas deliberadas —los temas arriba, el catálogo y JSK abajo— y el corte lo fuerza `.topic-break`, no el ancho de la ventana:

- **Libertad de Prensa** — ataques, censura, detenciones, informes de organismos especializados. Viene de la `category: libertad_prensa` de la fuente (CPJ, RSF, Artículo 19, Google Alerts, U.S. Press Freedom Tracker, Freedom of the Press Foundation, Free Press Action, IPYS, SNTP Venezuela, etc.).
- **Periodismo** — industria/oficio periodístico: tendencias, investigación académica, gremios (`category: periodismo`, ej. LatAm Journalism Review, Reuters Institute, SPJ, FIJ, Blueprints, Press Forward).
- **CPJ Américas** — solo lo que publica el CPJ para la región, en inglés y español. No viene de la `category` sino del campo `tab` de la fuente, que **suma** una pestaña en vez de reemplazar la de su categoría: los mismos items siguen apareciendo en Libertad de Prensa.
- **JSK Stanford** — noticias del John S. Knight Journalism Fellowships. También por `tab`, sobre `category: periodismo`. Es la única fuente con `no_expira: true`: publica por calendario académico y con el corte parejo de `MAX_AGE_DAYS` la pestaña quedaría vacía entre ciclos.
- **Medios en el Exilio** — notas de medios perseguidos que operan fuera de su país (`category: medios_exilio`). Son las únicas fuentes filtradas por tema: publican todo su periodismo y solo entra lo que toca libertad de expresión (ver abajo). De cada nota se conserva únicamente el titular y el enlace al medio, y **no entran a "Todos"**: viven solo en su pestaña (`OWN_TAB_ONLY` en `docs/app.js`).

### El filtro de los medios en el exilio

`es_libertad_de_prensa()` en `scripts/fetch_feeds.py` pide **dos señales**, no una. Con una sola lista de palabras se midió y no alcanza: "periodista" aparece en las firmas de casi cualquier nota, y "exilio" o "amenaza" son vocabulario político corriente en Nicaragua y El Salvador. Una nota entra si:

1. tiene un término **fuerte** e inequívoco en titular o resumen (`PRESS_FREEDOM_STRONG`: "libertad de prensa", "periodista amenazado", "acoso judicial", CPJ, RSF, Artículo 19…); **o**
2. nombra a la prensa **en el titular** (`PRESS_ACTOR`, o el nombre del propio medio) **y** hay un término de daño o exilio en titular o resumen (`PRESS_HARM`).

Que la señal de prensa tenga que estar en el titular es lo que da la precisión: las firmas y los créditos viven en el resumen. Medido el 2026-08-16: 100% de precisión sobre Confidencial y El Faro, y 100% de recall sobre las notas del CPJ del feed, que son prensa por definición.

Dos cosas descartadas por medición: **"censura" a secas** no sirve como término fuerte (traía una nota sobre una herida "censurada de los informes oficiales" de una muerte en prisión), y **el nombre del medio en el resumen** tampoco, porque aparece en el pie de todas sus notas.

## Enfoque geográfico: las Américas

El feed cubre las Américas, y hay dos filtros en `scripts/fetch_feeds.py` que lo sostienen, porque dos fuentes se salen de la región por naturaleza:

- **Convocatorias de GFMD** — GFMD recopila financiamiento de todo el mundo, y la mayoría de lo que publica es para Europa, los Balcanes o África. Se filtran por la región que ellos mismos declaran en el cuerpo (`Target Region:`) contra `AMERICAS_REGION`. Se conservan las globales, y también las que no declaran región: no poder determinarla no es razón para esconder una convocatoria que quizá aplica. Cada corrida imprime cuáles descartó.
- **Google Alerts** — sus consultas incluyen "Latin America", pero Google lo trata como sugerencia y no como filtro, y **las alertas en español no llevan ninguna restricción geográfica**. Un item de alerta se descarta solo si nombra una región de fuera (`NON_AMERICAS`) **y** ninguna de las Américas; si menciona ambas, se conserva (ej. un periodista venezolano detenido en España sigue siendo un caso de la región).

Hay además dos filtros de calidad sobre los items de alertas, ambos acotados a prioridad 4:

- **Enlaces a redes sociales** (`SOCIAL_HOSTS`) — Google Alerts indexa publicaciones de YouTube, Instagram, Facebook, TikTok y X igual que notas de medios. Revisadas con el usuario el 2026-08-15: son piezas de opinión, no reportería. No se aplica a las fuentes de organizaciones, porque ahí un enlace a un video propio sí es señal.
- **Desenvoltura de redirects** (`unwrap_redirect`) — las alertas no enlazan a la nota sino a `google.com/url?...&url=<destino>`. Se desenvuelve antes de canonicalizar, con tres efectos: el sitio enlaza al medio real y no a un redirect de Google, el dedupe exacto puede cruzar un item de alerta con la misma nota publicada por CPJ o RSF (antes nunca coincidían, porque todos los enlaces de alertas tenían host `google.com`), y el filtro de redes puede ver el dominio verdadero.

`NON_AMERICAS` deja fuera a propósito varios topónimos que colisionan con lugares de las Américas: **Georgia** (estado de EE.UU.), **Armenia** (capital del Quindío, Colombia), **India** ("mujer india") y **Asia** (nombre de pila). Por la misma razón "España" solo cuenta como país en formas inequívocas (`en España`, `español/a`) y no a secas — es un apellido corriente, y el filtro llegó a descartar una nota guatemalteca sobre "el periodista Diego España". Al tocar estas listas, correr el script y revisar la salida: imprime todo lo que descarta, precisamente para poder auditarlo.

## Oportunidades y Recursos

Las otras dos pestañas **no** salen del feed de noticias: leen `docs/data/opportunities.json`, que se arma mezclando dos cosas.

1. **Catálogo curado** (`config/opportunities.yaml`) — una entrada por convocatoria o recurso, escrita y verificada a mano, con `deadline`, `region`, `kind` y resumen propio.
2. **Convocatorias por RSS** — solo GFMD (`gfmd.info/fundings/feed/`). Es la única fuente revisada que publica un feed real de convocatorias. Sus items llevan `category: oportunidades` en `sources.yaml`, lo que hace que `fetch_feeds.py` los saque del pipeline de noticias antes del dedupe y los mande a este archivo.

Por qué esta separación: una convocatoria no es una noticia. Lo que importa es la fecha límite y si sigue abierta, no cuándo se publicó, así que ordenarlas por fecha de publicación y caducarlas a los 90 días (como hace el feed) sería incorrecto. El sitio calcula el estado —`Cierra en N días` / `Cerrada` / `Permanente`— **en el navegador** a partir del `deadline`, no al generar el JSON: el workflow corre cada 12 horas y una fecha calculada en el servidor quedaría desfasada justo el día del vencimiento. Las convocatorias vencidas no se borran; quedan al final, atenuadas, porque casi todas son anuales.

Para las convocatorias que llegan por RSS, el script intenta extraer la fecha límite del cuerpo del texto (`parse_deadline`). Va deliberadamente por precisión y no por cobertura: parte de cada fecha del texto y exige que la anteceda una expresión de cierre ("deadline", "must be submitted by"…) y que no la anteceda nada que delate otro tipo de evento ("conference", "webinar", "notified"…). Sin eso, tomaba la fecha de una conferencia como fecha límite. Las que no pasan el filtro se muestran como "Fecha en la convocatoria" y remiten al enlace original — mejor sin fecha que con una equivocada.

### Sitios de oportunidades sin RSS

De las 17 URLs revisadas el 2026-08-15, solo GFMD sirve como fuente automática. El resto está en el catálogo curado:

- **GIJN** (jobs y resource center) y **Pulitzer Center** — Cloudflare responde con un challenge de JS en todo el dominio, incluidos los `/feed/`. Tampoco funcionarían desde GitHub Actions.
- **IJNet** — tiene `rss.xml`, pero devuelve un feed de "destacados" de Drupal que mezcla notas de 2014-2018 sin orden cronológico. Inservible para monitoreo. (Sus URLs sí distinguen `/opportunity/` de `/story/`, por si algún día se justifica scrapear.)
- **NIHCM, MacArthur, Instrumentl, Lenfest** — sin RSS de ningún tipo.
- **Ida B. Wells Society** y **Lenfest** — tienen feed, pero quedaron `active: false` en `sources.yaml`: el primero no publica desde noviembre 2025 y son perfiles de miembros; el segundo trae una sola entrada.

### Agregar una oportunidad o un recurso

Agregar una entrada en `config/opportunities.yaml`, bajo `opportunities:` o `resources:`. El `id` es la clave y no se debe reutilizar ni renombrar. Poner `deadline` solo si hay una fecha exacta y verificada; si es rolling, anual o desconocida, dejarlo en `null` y explicarlo en `deadline_note`, que se muestra tal cual. Conviene repasar los `deadline` una vez por trimestre.

## Agregar una fuente

Agregar una entrada en `config/sources.yaml` con `active: true`. Campos: `id`, `name`, `url` (RSS/Atom), `language` (`en`/`es`), `country` (o `null` si es regional), `priority` (1=más autorizada, para desempatar duplicados — 1=CPJ, 2=RSF, 3=orgs regionales/otras, 4=Google Alerts), `category` (`libertad_prensa`, `periodismo` u `oportunidades`, que define a qué pestaña va).

Antes de agregarla, verificar a mano que la URL sirva un feed real: código 200, `content-type` de XML/RSS/Atom y contenido reciente. Varios sitios que parecen tener feed devuelven 404, redirigen al home o sirven contenido viejo desordenado.

**Que funcione en tu máquina no basta.** Algunos sitios responden 200 desde una conexión doméstica y 403 desde los rangos de IP de datacenter que usa GitHub Actions — es bloqueo por IP y no se arregla cambiando el User-Agent. Le pasó a SPJ (`www.spj.org/feed/`), que quedó `active: false` por eso. Después de agregar una fuente conviene mirar la primera corrida del workflow (`gh run view --log | grep Wrote`) y confirmar que el conteo de fuentes OK sea el esperado, no solo probar en local.

Si un sitio no publica RSS/Atom (ej. requiere JS, o lo desactivó deliberadamente), no se puede meter al pipeline automático — se agrega como enlace de revisión manual en el footer de `docs/index.html`, igual que NoNosCallarán, SIP/IAPA, IPI, NPPA y la CIDH.

## Google Alerts

Las 20 alertas (10 en inglés, 10 en español) ya están creadas en la cuenta de Google del usuario y activas en `config/sources.yaml` (prioridad 4, `alert_en_*` / `alert_es_*`), configuradas con **Sources: Automatic**, **How many: All results**, **Deliver to: RSS feed**.

### No agregar exclusiones geográficas a estas consultas

Se probó el 2026-08-15 y **hay que no repetirlo**. Se les agregó a las 20 un sufijo del tipo `-Gaza -Israel -Ucrania -Rusia -China …` para atajar el ruido de Medio Oriente y Asia. El resultado: **19 de las 20 alertas pasaron a devolver 0 resultados**, y la única que sobrevivió cayó de 18 items a 9.

La causa es que el operador `-término` de Google aplica a **toda la página indexada, no al artículo**. Las páginas de medios mencionan Gaza, Israel, Ucrania o China en barras laterales, widgets de "lo más leído" y notas relacionadas, así que excluir esos términos elimina buena parte de los sitios de noticias, sin importar de qué trate la nota. Se revirtieron las 20 y las alertas se recuperaron.

El filtro geográfico vive en el pipeline (`NON_AMERICAS`, ver *Enfoque geográfico*), donde se evalúa solo contra el título y el resumen del item — que es el texto de la nota y no el de la página entera. Es el lugar correcto para esto.

Otras dos cosas verificadas en esa prueba, útiles si hay que volver a tocar las alertas:

- Editar la consulta de una alerta **no cambia la URL de su feed RSS**: los 20 IDs siguieron coincidiendo con `config/sources.yaml`. No hay que tocar el YAML al ajustar consultas.
- Editar una alerta **no vacía su feed**: conserva los items anteriores. Si tras un cambio el feed queda vacío, es que la consulta dejó de matchear, no que se esté repoblando.

La cuenta tiene además 4 alertas ajenas al feed (`Congreso de Guatemala`, `Ley Electoral y Partidos Políticos`, `Perenco`, `Sonia Gutiérrez Raguay`) y 2 de "Me on the web". No forman parte de este proyecto y no deben tocarse.

### Aflojado de las consultas sin resultados (2026-08-15)

11 de las 20 alertas devolvían **0 resultados**: pedían frases exactas entre comillas (`"journalist attacked"`, `"periodista agredido"`) que exigen esas palabras pegadas y en ese orden, cosa que casi no ocurre en titulares reales — se escribe "attack on journalist", "periodista fue agredida", "agreden a reportero". Se reescribieron quitando la adyacencia obligatoria y conservando el núcleo temático, con sinónimos. Las 9 que sí producían contenido **no se tocaron**.

A diferencia del experimento con exclusiones, este cambio solo puede sumar: las 9 alertas productivas conservaron sus conteos exactos (55 entradas antes y después). Pero **el efecto no se ve el mismo día**: una consulta nueva arranca sin historial y Google va poblando el feed a medida que rastrea coincidencias nuevas. Para evaluar si funcionó, correr el script unos días después y mirar `items_fetched` por fuente en `docs/data/status.json`.

Marcadas con → las 11 reescritas.

**Inglés:**
1. `"journalist killed" Latin America`
2. `"journalist murdered" OR "reporter killed" Latin America` → `(journalist OR reporter) (murdered OR slain) Latin America`
3. `"journalist attacked" OR "journalist assaulted" Latin America` → `journalist attacked OR assaulted OR beaten Latin America`
4. `"journalist threatened" OR "journalist harassed" Latin America` → `journalist threatened OR harassed OR intimidated Latin America`
5. `"journalist detained" OR "journalist arrested" Latin America` → `journalist detained OR arrested OR jailed Latin America`
6. `"journalist kidnapped" Latin America`
7. `"press freedom" attack Latin America`
8. `journalist censored OR "media censorship" Latin America` → `journalist censored OR censorship Latin America`
9. `journalist "legal harassment" OR SLAPP journalist Latin America` → `journalist SLAPP OR defamation OR lawsuit Latin America`
10. `journalist exiled OR "forced into exile" journalist Latin America`

**Español:**
1. `"periodista asesinado" OR "periodista asesinada"`
2. `"periodista amenazado" OR "periodista amenazada"`
3. `"periodista agredido" OR "periodista atacado"` → `periodista agredido OR agredida OR atacado OR atacada OR agresión`
4. `"periodista detenido" OR "periodista detenida"` → `periodista detenido OR detenida OR arrestado OR arrestada`
5. `"periodista secuestrado" OR "periodista secuestrada"` → `periodista secuestrado OR secuestrada OR secuestro`
6. `"periodista desaparecido"`
7. `censura periodista OR "censura a periodistas"`
8. `"periodista demandado" OR "demanda contra periodista"` → `periodista demandado OR querella OR difamación OR "demanda contra"`
9. `"periodista exiliado" OR periodista exilio`
10. `"reportero agredido" OR "reportera agredida"` → `(reportero OR reportera) (agredido OR agredida OR atacado OR atacada)`

Para agregar/editar alertas: ir a [google.com/alerts](https://www.google.com/alerts) → "My alerts". La URL del feed RSS no aparece en la pantalla de creación — hay que hacer clic en el ícono RSS junto a la alerta para copiarla, y pegarla en `config/sources.yaml`.

Si hay que automatizar la edición, dos detalles de la UI (es una app de Closure): los botones son `span[role=button][title="Edit"]`, y un `click()` simple sobre "Update alert" **no** guarda — hace falta la secuencia `pointerdown/mousedown/pointerup/mouseup/click`. El valor del input va con el setter nativo de `HTMLInputElement.prototype.value` más eventos `input`/`keyup`/`change`. Y conviene usar lista blanca explícita de consultas, porque el botón "Delete" está pegado al de "Edit" y en la cuenta hay alertas ajenas al proyecto.

## Fuentes sin RSS (revisión manual)

Listadas en el footer de `docs/index.html`:

- **NoNosCallarán** — colectivo guatemalteco sin sitio propio, activo solo en X: [@NoNosCallaranGT](https://x.com/NoNosCallaranGT).
- **SIP/IAPA** ([en.sipiapa.org](https://en.sipiapa.org)) — sin RSS detectado (CMS propio, sin autodiscovery ni rutas estándar).
- **IPI** ([ipi.media](https://ipi.media)) — WordPress con el feed nativo desactivado (`/feed/` y `?feed=rss2` redirigen al home).
- **NPPA** ([nppa.org](https://nppa.org)) — sitio Next.js, sin ruta de feed.
- **CIDH – Relatoría Especial para la Libertad de Expresión** ([oas.org/es/cidh/expresion](https://www.oas.org/es/cidh/expresion/index.asp)) — sitio institucional sin RSS.

Ninguna se integra al pipeline automático — revisar manualmente.

**Dos feeds que no están donde se los espera**, anotados para no volver a buscarlos:

- **JSK Stanford** — el sitio es Drupal y no publica autodiscovery. La ruta real es `/news/rss`, que aparece en el `drupal-settings-json` del HTML de `/news` como `view_base_path`.
- **El Faro** — `elfaro.net` devuelve 404 desde que migraron el sitio; el feed vivo es `https://beta.elfaro.net/rss.xml`. Sus `<link>` apuntan al host interno de Superdesk donde se arma el sitio, y se reescriben en `LINK_HOST_REWRITES` (`scripts/fetch_feeds.py`). El día que El Faro complete la migración a su dominio, la URL del feed y la reescritura se rompen juntas.

## Identidad visual

`logos/` tiene los PNG originales (perfil circular, logo cuadrado, banner ancho). `docs/assets/` tiene copias redimensionadas/comprimidas con `sips`+`pngquant` para el sitio: `favicon.png` (128×128, ícono de pestaña) y `banner.png` (1600×533, header, centrado). El logo cuadrado no se usa en el sitio; queda disponible en `logos/` para redes sociales u otros usos.

**La paleta sale del banner.** El fondo de la página (`--bg: #f8f3f0`) es el crema exacto que ocupa el 76% de los píxeles del banner, así el logo no se recorta contra la página sino que se funde con ella. El resto de la paleta (bordes, texto atenuado, fondo de notas) se corrió al mismo lado cálido para que no queden grises fríos al lado del crema. `--surface` (#fffdfc) es un tono apenas más claro, para que los campos y botones se despeguen del fondo.

**El sitio tiene un solo tema, a propósito — no hay modo oscuro.** `banner.png` no tiene transparencia: trae horneado su fondo crema y su tinta es casi negra. En modo oscuro quedaba como un bloque claro flotando sobre la página, que es exactamente la desconexión que se quiso eliminar. Para reactivarlo haría falta una versión del logo con tinta clara y fondo transparente; con eso, restaurar el bloque `@media (prefers-color-scheme: dark)` que se quitó de `docs/style.css`.

Detalle de CSS a tener presente: el archivo declara `[hidden] { display: none !important; }`. El atributo `hidden` lo pisa cualquier regla que declare `display`, y `.kind-filter` es `flex` — sin esa regla, el filtro por tipo de oportunidad se cuela en todas las pestañas.

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
