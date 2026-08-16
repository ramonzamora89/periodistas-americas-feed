#!/usr/bin/env python3
"""Fetch, normalize, dedupe and publish the journalist-attacks feed.

Reads config/sources.yaml, fetches every active RSS/Atom source, merges
duplicate coverage of the same case (exact link match + fuzzy title match),
and writes docs/data/feed.json + docs/data/status.json for the static site.
"""

from __future__ import annotations

import calendar
import hashlib
import html
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "sources.yaml"
OPPS_CONFIG_PATH = ROOT / "config" / "opportunities.yaml"
FEED_OUT_PATH = ROOT / "docs" / "data" / "feed.json"
STATUS_OUT_PATH = ROOT / "docs" / "data" / "status.json"
OPPS_OUT_PATH = ROOT / "docs" / "data" / "opportunities.json"

USER_AGENT = "PeriodistasAmericasFeedBot/1.0 (+https://github.com/)"
REQUEST_TIMEOUT_SECONDS = 15

MAX_AGE_DAYS = 90
MAX_ITEMS = 500

FUZZY_WINDOW_HOURS = 72
FUZZY_JACCARD_THRESHOLD = 0.5
FUZZY_MIN_TOKENS = 4

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "mc_cid", "mc_eid",
}

STOPWORDS = {
    "journalist", "periodista", "periodistas", "reportero", "reportera",
    "killed", "murdered", "asesinado", "asesinada", "muere", "murio",
    "died", "attack", "attacked", "ataque", "atacado", "atacada",
    "detained", "detenido", "detenida", "the", "a", "an", "de", "en",
    "el", "la", "los", "las", "por", "for", "in", "on", "and", "y",
    "con", "with", "que", "es", "un", "una", "to", "of", "su", "sus",
}

# Medios que operan en el exilio. A diferencia del resto de las fuentes, estos
# publican TODO su periodismo —política y economía nacional en su mayoría— así
# que solo entra lo que toca libertad de expresión. Sin este filtro Confidencial
# solo ya aporta 60 notas por corrida.
EXILE_MEDIA_CATEGORY = "medios_exilio"

# El filtro pide DOS señales, no una. Una sola lista de palabras se midió y no
# alcanza: "periodista" aparece en las firmas y en las citas de casi cualquier
# nota, y "exilio" o "amenaza" son vocabulario corriente de la política
# nicaragüense y salvadoreña. Filtrando por una sola señal, de 80 notas pasaban
# 5 y solo 2 eran del tema.
#
# Pasa una nota si:
#   1. contiene un término FUERTE —inequívoco, casi siempre multipalabra— en el
#      titular o el resumen; o
#   2. nombra a la prensa EN EL TITULAR y además hay un término de daño o exilio
#      en el titular o el resumen.
#
# Que la señal de prensa tenga que estar en el titular es lo que da la
# precisión: las firmas y los créditos viven en el resumen, nunca en el titular.
#
# Medido el 2026-08-16: 100% de precisión sobre Confidencial y El Faro, y 100%
# de recall sobre las notas del CPJ del feed, que son prensa por definición.
PRESS_FREEDOM_STRONG = re.compile(
    r"(libertad de (prensa|expresi[oó]n|informaci[oó]n)"
    r"|press freedom|freedom of (the )?(press|expression)"
    r"|censura (previa|medi[aá]tica|a (la prensa|periodis|los? medios?))"
    r"|censura(r|do|da)? (a|de) (la prensa|periodis|los? medios?)"
    r"|press censorship|censorship of (the )?(press|media|journalis)"
    r"|periodistas? (exiliad|amenazad|detenid|asesinad|agredid|encarcelad|preso)"
    r"|exilio period[ií]stico|medios? (en el )?exilio|exiled (journalist|media|news)"
    r"|acoso judicial|criminalizaci[oó]n de (la prensa|periodis)"
    r"|persecuci[oó]n (a|de) (la prensa|periodis)"
    r"|secreto profesional|confidencialidad de (la )?fuente|source confidentiality"
    r"|\bCPJ\b|Comit[eé] para la Protecci[oó]n de los Periodistas"
    r"|\bRSF\b|Reporteros Sin Fronteras|Fundamedios|Art[ií]culo 19|ARTICLE 19)",
    re.IGNORECASE,
)

# Señal 1: alguien de la prensa. Se exige en el titular.
PRESS_ACTOR = re.compile(
    r"\b(periodist[ao]s?|period[ií]stic[oa]s?|reporter[oa]s?|prensa|periodismo|cronista"
    r"|corresponsal(es)?|comunicador(es|as)?|locutor(a|es|as)?"
    r"|medios? (de comunicaci[oó]n|independientes?|digitales?)"
    r"|journalis(t|ts|m)|newsroom[s]?|reporter[s]?|press|news outlet"
    r"|media (director|worker))\b",
    re.IGNORECASE,
)

# Señal 2: qué le pasó. Vale en el titular o el resumen.
PRESS_HARM = re.compile(
    r"\b(exili(o|ad[oa]s?)|destierro|desterrad[oa]s?|exile[d]?"
    r"|asesinat|asesinad[oa]s?|homicidio|murder(ed)?|killed|killing"
    r"|agresi[oó]n|agredid|atacad[oa]s?|attack(s|ed)?|violencia contra"
    r"|detenci[oó]n|detenid[oa]s?|arrest(ed|o)?|encarcelad|jailed|imprison"
    r"|secuestr(o|ad[oa]s?)|abducted|kidnapp|desaparici[oó]n|desaparecid[oa]s?|disappear"
    r"|demandad[oa]s?|difamaci[oó]n|defamation|querella|sued|lawsuit"
    r"|allanamiento|confiscaci[oó]n|incautaci[oó]n|clausura|expulsi[oó]n|expulsad"
    r"|criminaliza|persecuci[oó]n|persegui|impunidad|impunity"
    r"|amenaz(a|as|ad[oa]s?)|threat(s|ened)?|acoso|harass|hostigamiento|intimidaci[oó]n"
    r"|censur|censorship|bloqueo|shut down)",
    re.IGNORECASE,
)


# El Faro publica en un solo feed sus versiones en español y en inglés, y las
# distingue con un /en/ al principio de la ruta. Sin esto ambas quedan
# etiquetadas con el idioma declarado de la fuente y el filtro ES/EN del sitio
# las manda a la misma pestaña. Las dos versiones se conservan a propósito: son
# la misma nota, pero el sitio ofrece las dos.
def detectar_idioma(link: str, por_defecto: str) -> str:
    return "en" if urlsplit(link).path.startswith("/en/") else por_defecto


def es_libertad_de_prensa(titulo: str, resumen: str, medio: str | None = None) -> bool:
    """¿La nota de un medio en el exilio trata sobre libertad de expresión?"""
    texto = f"{titulo} {resumen}"
    if PRESS_FREEDOM_STRONG.search(texto):
        return True
    # El nombre del medio en su propio titular cuenta como señal de prensa: es
    # una nota del medio sobre sí mismo. Solo sirve en el titular — en el
    # resumen aparece en el pie de TODAS sus notas y no distingue nada.
    nombra_prensa = bool(PRESS_ACTOR.search(titulo)) or bool(
        medio and re.search(rf"\b{re.escape(medio)}\b", titulo, re.IGNORECASE)
    )
    return nombra_prensa and bool(PRESS_HARM.search(texto))

# Las fuentes con esta category no van al feed de noticias: sus items se
# desvían a opportunities.json y se mezclan con el catálogo curado.
OPPORTUNITY_CATEGORY = "oportunidades"

# El feed es de las Américas. GFMD recopila convocatorias de todo el mundo y la
# mayoría son para Europa, los Balcanes o África, así que se filtran por la
# región que ellos mismos declaran en el cuerpo ("Target Region: West Africa").
# Se conservan las globales: una convocatoria abierta al mundo sí aplica acá.
AMERICAS_REGION = re.compile(
    r"global|worldwide|international|any country|all countries"
    r"|america|américa|americas|latin|latino|caribbean|caribe|hemisphere"
    r"|argentin|boliv|brazil|brasil|chile|colomb|costa rica|cuba|dominican"
    r"|ecuador|el salvador|guatemal|hait|hondur|jamaica|m[eé]xic|mexico"
    r"|nicaragu|panam|paraguay|per[uú]|puerto rico|uruguay|venezuel"
    r"|united states|u\.s\.|usa\b|canada|canad[aá]",
    re.IGNORECASE,
)

# Marcadores geográficos fuertes de fuera de las Américas, para los items de
# Google Alerts: sus consultas dicen "Latin America" pero Google lo trata como
# sugerencia, no como filtro, y las alertas en español no llevan región alguna.
NON_AMERICAS = re.compile(
    r"\b(gaza|israel|israeli|palestin|palestino|hamas|west bank|cisjordania"
    r"|netanyahu|l[ií]bano|lebanon|syria|siria|iran|ir[aá]n|iraq|yemen|saudi"
    r"|arabia saud|afghan|afgan|talib[aá]n|pakistan|pakist[aá]n|india\b|hindu"
    r"|china|chinese|chino|hong kong|myanmar|birmania|vietnam|filipin"
    r"|philippin|indonesia|thailand|tailandia|bangladesh|nepal|sri lanka"
    r"|corea|korea|jap[oó]n|japan|turqu[ií]a|turkey|turkish|egipto|egypt"
    r"|libia|libya|sud[aá]n|sudan|somalia|etiop[ií]a|ethiopia|nigeria|kenya"
    r"|kenia|uganda|tanzania|zimbabwe|niger|mali|senegal|bagdad|baghdad"
    r"|rusia|russia|russian|ruso|ucrania"
    r"|ukraine|belar[uú]s|serbia|hungr[ií]a|hungary|polonia|poland|balcan"
    r"|balkan|azerbaiy|azerbaijan|kazaj|uzbek"
    # "España" a secas es también un apellido corriente ("el periodista Diego
    # España"), así que solo se acepta como país en formas inequívocas.
    r"|(?:en|de|desde|hacia|para)\s+espa[nñ]a|espa[nñ]ol[ao]s?"
    r"|medio oriente|middle east|[aá]frica|asi[aá]tico)\b",
    re.IGNORECASE,
)
# Deliberadamente fuera de la lista, por colisión con lugares de las Américas:
# Georgia (estado de EE.UU.), Armenia (capital del Quindío, Colombia), India
# ("mujer india"), Asia (nombre de pila). El costo de descartar por error una
# nota de la región es mayor que el de dejar pasar una de fuera.
# Para decidir si un item de alerta es de la región hace falta una lista más
# estricta que AMERICAS_REGION, que se usa contra el campo "Target Region" de
# una convocatoria y puede permitirse ser laxa. Acá se evalúa prosa: el
# fragmento suelto "america" matcheaba dentro de "American", y una nota titulada
# "American missionary kidnapped in Niger" quedaba clasificada como de las
# Américas pese a hablar de Níger, Nigeria y Bagdad. Por eso van nombres de
# país y gentilicios completos, y no "american" a secas.
AMERICAS_NEWS = re.compile(
    r"\b(am[eé]ricas?|latin\s?am[eé]rica|latinoam[eé]rica|hemisferio occidental"
    r"|estados unidos|united states|u\.s\.a?\.?|ee\.?\s?uu\.?|canad[aá]|canadian"
    r"|m[eé]xico|mexico|mexican[oa]s?|colombia|colombian[oa]s?|brasil|brazil"
    r"|brasile[nñ][oa]s?|brazilian|venezuela|venezolan[oa]s?|venezuelan"
    r"|cuba|cuban[oa]s?|hait[ií]|haitian[oa]s?|guatemala|guatemaltec[oa]s?"
    r"|hondura?s|hondure[nñ][oa]s?|nicaragua|nicarag[uü]ense|el salvador"
    r"|salvadore[nñ][oa]s?|costa rica|costarricense|panam[aá]|paname[nñ][oa]s?"
    r"|ecuador|ecuatorian[oa]s?|per[uú]|peruan[oa]s?|bolivia|bolivian[oa]s?"
    r"|chile|chilen[oa]s?|argentina|argentin[oa]s?|paraguay|paraguay[oa]s?"
    r"|uruguay|uruguay[oa]s?|rep[uú]blica dominicana|dominican republic"
    r"|puerto rico|puertorrique[nñ][oa]s?|jamaica|belice|belize|caribe|caribbean)\b",
    re.IGNORECASE,
)
GOOGLE_ALERTS_PRIORITY = 4

# Google Alerts indexa publicaciones de redes sociales igual que notas de
# medios. Revisadas con el usuario el 2026-08-15: son piezas de opinión, no
# reportería, así que se descartan. Solo aplica a los items de alertas — una
# organización que enlaza a un video propio sí es señal.
SOCIAL_HOSTS = re.compile(
    r"^(?:[\w-]+\.)*(?:youtube\.com|youtu\.be|instagram\.com|facebook\.com"
    r"|fb\.watch|tiktok\.com|twitter\.com|x\.com|threads\.net)$",
    re.IGNORECASE,
)


def is_social_link(link: str) -> bool:
    return bool(SOCIAL_HOSTS.match(urlsplit(unwrap_redirect(link)).netloc))

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}

# GFMD escribe la fecha límite en prosa dentro del cuerpo de la convocatoria
# ("the deadline is Monday, September 14, 2026", "deadline ... is 20 September
# 2026 at 23:59 CET"). Buscamos una fecha explícita en la ventana de texto que
# sigue a la palabra deadline; si no hay uno inequívoco, se deja en null antes
# que arriesgar una fecha equivocada en una convocatoria.
# Cubre "20 September 2026", "September 20, 2026" y "the 20th of September, 2026".
DATE_ANY = re.compile(
    r"\b(?:"
    r"(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(" + "|".join(MONTHS) + r")"
    r"|(" + "|".join(MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?"
    r"),?\s+(\d{4})\b",
    re.IGNORECASE,
)

# Una convocatoria nombra varias fechas: la de cierre, la de la conferencia, la
# del webinar informativo, la de aviso a los seleccionados. Para no publicar una
# fecha límite equivocada — peor que no publicar ninguna — se parte de cada
# fecha encontrada y se mira el texto que la antecede: se acepta solo si ahí
# aparece una expresión de cierre y no aparece nada que delate otro tipo de
# evento.
DEADLINE_CUE = re.compile(
    r"deadline"
    r"|must\s+be\s+submitted"
    r"|submitted?\b.{0,50}?\bby\b"
    r"|applications?\b.{0,40}?\b(?:by|before|until)\b"
    r"|appl(?:y|ying)\s+(?:online\s+)?(?:by|before|until)"
    r"|closing\s+date"
    r"|applications?\s+close"
    r"|due\s+(?:by|on)"
    r"|open\s+until",
    re.IGNORECASE | re.DOTALL,
)
NOT_A_DEADLINE = re.compile(
    r"conference|session|webinar|workshop|notif|announce|question"
    r"|implementation|lasting|awarded|winners|published|held\b|begins?\b",
    re.IGNORECASE,
)
LOOKBEHIND_CHARS = 110
REGION_LABEL = re.compile(
    r"(?:Target\s+Region|Region)\s*:?\s*</strong>\s*([^<]{2,60})", re.IGNORECASE
)
# La lista de metadata con la que GFMD abre cada convocatoria.
METADATA_LIST = re.compile(
    r"<ul>(?=(?:(?!</ul>).)*?(?:Eligibility|Target\s+Region|Application\s+Language))"
    r".*?</ul>",
    re.IGNORECASE | re.DOTALL,
)
# Cierre que WordPress agrega al final del extracto.
TRAILING_BOILERPLATE = re.compile(
    r"\s*The post .{0,120}? appeared first on .{0,60}?\.\s*$", re.IGNORECASE
)


@dataclass
class Source:
    id: str
    name: str
    url: str
    language: str
    country: str | None
    priority: int
    category: str
    active: bool
    # Pestaña propia de la fuente, además de la que le da su category. Sirve
    # para las pestañas que agrupan por medio y no por tema (CPJ Américas, JSK).
    tab: str | None = None
    # Exime a la fuente del corte por antigüedad de MAX_AGE_DAYS. Para fuentes
    # que publican por temporada y cuyo archivo vale aunque esté viejo.
    no_expira: bool = False


@dataclass
class Item:
    id: str
    title: str
    link: str
    published: str
    published_ts: float
    summary: str
    source: str
    source_id: str
    language: str
    country: str | None
    priority: int
    category: str
    topics: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    also_reported_by: list[dict] = field(default_factory=list)
    # Heredado de la fuente: si es True, el item no caduca a los MAX_AGE_DAYS.
    no_expira: bool = False
    # Solo se llenan para items de fuentes con category "oportunidades".
    deadline: str | None = None
    region: str | None = None


def load_sources() -> list[Source]:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    sources = []
    for entry in raw.get("sources", []):
        if not entry.get("active", False):
            continue
        sources.append(
            Source(
                id=entry["id"],
                name=entry["name"],
                url=entry["url"],
                language=entry["language"],
                country=entry.get("country"),
                priority=int(entry["priority"]),
                category=entry["category"],
                active=True,
                tab=entry.get("tab"),
                no_expira=bool(entry.get("no_expira", False)),
            )
        )
    return sources


def load_catalog() -> tuple[list[dict], list[dict]]:
    """Lee el catálogo curado de oportunidades y recursos."""
    if not OPPS_CONFIG_PATH.exists():
        return [], []
    with OPPS_CONFIG_PATH.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return raw.get("opportunities") or [], raw.get("resources") or []


def parse_deadline(text: str) -> str | None:
    """Extrae una fecha límite en ISO del cuerpo de una convocatoria, o None.

    Una convocatoria puede nombrar varias fechas (los ciclos del año, la fecha
    de aviso a los seleccionados). Se juntan todas las que aparecen cerca de la
    palabra "deadline" y se devuelve la más próxima que todavía no pasó; si ya
    pasaron todas, la más reciente, que es la que dice cuándo cerró.
    """
    text = text or ""
    explicit: list[str] = []
    inferred: list[str] = []

    for match in DATE_ANY.finditer(text):
        day = match.group(1) or match.group(4)
        month = match.group(2) or match.group(3)
        year = match.group(5)
        try:
            parsed = datetime(int(year), MONTHS[month.lower()], int(day)).date()
        except ValueError:
            continue

        before = text[max(0, match.start() - LOOKBEHIND_CHARS):match.start()]
        if NOT_A_DEADLINE.search(before) or not DEADLINE_CUE.search(before):
            continue
        # "deadline" dicho con todas las letras vale más que una perífrasis.
        target = explicit if "deadline" in before.lower() else inferred
        target.append(parsed.isoformat())

    today = datetime.now(tz=timezone.utc).date().isoformat()
    for candidates in (explicit, inferred):
        if not candidates:
            continue
        future = sorted(d for d in candidates if d >= today)
        return future[0] if future else max(candidates)
    return None


def extract_opportunity_meta(entry) -> tuple[str | None, str | None, str | None]:
    """Saca fecha límite, región y un resumen limpio de una convocatoria."""
    body = ""
    for content in entry.get("content") or []:
        body += content.get("value") or ""
    if not body:
        body = entry.get("summary") or entry.get("description") or ""

    region = None
    match = REGION_LABEL.search(body)
    if match:
        region = strip_html(match.group(1)).strip(" :–-") or None

    # GFMD abre cada convocatoria con una lista de metadata (Eligibility,
    # Target Region, Application Language). Ya la leímos por separado, así que
    # se quita del resumen: sin esto la tarjeta empieza con "Eligibility: USA
    # journalists specialised in health Target Region: North America…" en vez
    # de con la descripción real.
    summary_html = METADATA_LIST.sub("", body, count=1)
    summary = strip_html(summary_html)
    summary = TRAILING_BOILERPLATE.sub("", summary).strip()
    if len(summary) > 300:
        summary = summary[:297].rstrip() + "..."

    return parse_deadline(strip_html(body)), region, summary or None


def unwrap_redirect(link: str) -> str:
    """Devuelve el destino real de un enlace envuelto por Google Alerts.

    Las alertas no enlazan a la nota sino a
    `google.com/url?...&url=<destino>`. Sin desenvolverlo, todos los items de
    alertas comparten host google.com: el dedupe exacto nunca los cruza con la
    nota original publicada por CPJ o RSF, y no hay forma de saber a qué sitio
    apuntan realmente.
    """
    parts = urlsplit(link)
    if parts.netloc.lower() not in {"google.com", "www.google.com"}:
        return link
    if parts.path not in {"/url", "/url/"}:
        return link
    params = dict(parse_qsl(parts.query))
    target = params.get("url") or params.get("q")
    return target if target and target.startswith(("http://", "https://")) else link


# El Faro migró su sitio a beta.elfaro.net, pero su RSS todavía enlaza al host
# interno de Superdesk donde se arma. Mandar al lector ahí sería mandarlo al
# staging del medio; con el host corregido la nota resuelve 200, y con
# elfaro.net a secas da 404. Si algún día El Faro completa la migración, esta
# reescritura y la URL del feed en sources.yaml se rompen juntas.
LINK_HOST_REWRITES = {
    "elfaro-pwa.superdesk.pro": "beta.elfaro.net",
}


def rewrite_host(link: str) -> str:
    parts = urlsplit(link)
    replacement = LINK_HOST_REWRITES.get(parts.netloc.lower())
    if not replacement:
        return link
    return urlunsplit(parts._replace(netloc=replacement))


def canonicalize_link(link: str) -> str:
    parts = urlsplit(unwrap_redirect(link))
    scheme = "https"
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/")
    query_pairs = [
        (k, v) for k, v in parse_qsl(parts.query) if k.lower() not in TRACKING_PARAMS
    ]
    query = urlencode(sorted(query_pairs))
    return urlunsplit((scheme, netloc, path, query, ""))


def strip_html(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^<]+?>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_published(entry) -> tuple[str, float]:
    struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if struct:
        ts = calendar.timegm(struct)
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.isoformat(), ts
    now = datetime.now(tz=timezone.utc)
    return now.isoformat(), now.timestamp()


def normalize_entries(source: Source, feed) -> list[Item]:
    items = []
    for entry in feed.entries:
        link = rewrite_host(unwrap_redirect(entry.get("link", "")))
        if not link:
            continue
        canonical = canonicalize_link(link)
        item_id = hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16]
        published, published_ts = parse_published(entry)
        summary = strip_html(entry.get("summary") or entry.get("description") or "")
        if len(summary) > 300:
            summary = summary[:297].rstrip() + "..."
        tags = [t.get("term") for t in entry.get("tags", []) if t.get("term")]
        title = strip_html(entry.get("title", ""))
        language = source.language

        if source.category == EXILE_MEDIA_CATEGORY:
            language = detectar_idioma(link, source.language)
            # "El Faro (El Salvador, en el exilio)" -> "El Faro"
            medio = source.name.split(" (")[0]
            if not es_libertad_de_prensa(title, summary, medio):
                continue
            # El resumen se usó para filtrar y acá se descarta: la tarjeta de un
            # medio en el exilio es solo titular, fuente, fecha y el enlace a la
            # nota original. renderItem() omite el párrafo si viene vacío.
            summary = ""

        topics = [source.category]
        if source.tab:
            topics.append(source.tab)

        deadline = region = None
        if source.category == OPPORTUNITY_CATEGORY:
            deadline, region, clean_summary = extract_opportunity_meta(entry)
            if clean_summary:
                summary = clean_summary

        items.append(
            Item(
                id=item_id,
                title=title,
                link=link,
                published=published,
                published_ts=published_ts,
                summary=summary,
                source=source.name,
                source_id=source.id,
                language=language,
                country=source.country,
                priority=source.priority,
                category=source.category,
                topics=topics,
                tags=tags,
                no_expira=source.no_expira,
                deadline=deadline,
                region=region,
            )
        )
    return items


def dedupe_exact(items: list[Item]) -> list[Item]:
    items = sorted(items, key=lambda i: i.published_ts)
    by_id: dict[str, Item] = {}
    for item in items:
        existing = by_id.get(item.id)
        if existing is None:
            by_id[item.id] = item
        else:
            existing.also_reported_by.append({"source": item.source, "link": item.link})
    return list(by_id.values())


def normalize_title_tokens(title: str) -> tuple[set[str], set[str]]:
    notable = {
        tok for tok in re.findall(r"[A-Za-zÀ-ÿ]{4,}", title) if tok[0].isupper()
    }
    normalized = unicodedata.normalize("NFKD", title.lower())
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    tokens = {tok for tok in normalized.split() if tok not in STOPWORDS}
    return tokens, notable


def dedupe_fuzzy(items: list[Item]) -> list[Item]:
    items = sorted(items, key=lambda i: i.published_ts)
    token_cache = {item.id: normalize_title_tokens(item.title) for item in items}
    merged_away: set[str] = set()

    for i, item_a in enumerate(items):
        if item_a.id in merged_away:
            continue
        tokens_a, notable_a = token_cache[item_a.id]
        if len(tokens_a) < FUZZY_MIN_TOKENS:
            continue
        for item_b in items[i + 1:]:
            if item_b.id in merged_away or item_b.id == item_a.id:
                continue
            if abs(item_b.published_ts - item_a.published_ts) > FUZZY_WINDOW_HOURS * 3600:
                continue
            tokens_b, notable_b = token_cache[item_b.id]
            if len(tokens_b) < FUZZY_MIN_TOKENS:
                continue

            union = tokens_a | tokens_b
            if not union:
                continue
            jaccard = len(tokens_a & tokens_b) / len(union)
            if jaccard < FUZZY_JACCARD_THRESHOLD:
                continue
            if not (notable_a & notable_b):
                continue

            primary, secondary = (
                (item_a, item_b)
                if (item_a.priority, item_a.published_ts) <= (item_b.priority, item_b.published_ts)
                else (item_b, item_a)
            )
            primary.also_reported_by.append({"source": secondary.source, "link": secondary.link})
            primary.also_reported_by.extend(secondary.also_reported_by)
            merged_away.add(secondary.id)
            if secondary.id == item_a.id:
                break

    return [item for item in items if item.id not in merged_away]


def fetch_source(source: Source) -> tuple[list[Item], dict]:
    try:
        response = requests.get(
            source.url,
            timeout=REQUEST_TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
        if parsed.bozo and not parsed.entries:
            raise ValueError(f"unparseable feed: {parsed.bozo_exception}")
        items = normalize_entries(source, parsed)
        return items, {
            "id": source.id,
            "name": source.name,
            "ok": True,
            "items_fetched": len(items),
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 - deliberately broad, one bad source shouldn't abort the run
        return [], {
            "id": source.id,
            "name": source.name,
            "ok": False,
            "items_fetched": 0,
            "error": str(exc),
        }


def catalog_entry_to_dict(entry: dict, origin: str = "curado") -> dict:
    return {
        "id": entry["id"],
        "name": entry["name"],
        "org": entry.get("org"),
        "url": entry["url"],
        "url_es": entry.get("url_es"),
        "kind": entry.get("kind"),
        "language": entry.get("language", "en"),
        "region": entry.get("region"),
        "deadline": entry.get("deadline"),
        "deadline_note": entry.get("deadline_note"),
        "summary": (entry.get("summary") or "").strip(),
        "origin": origin,
        "published": None,
        "verified": entry.get("verified"),
    }


def opportunity_item_to_dict(item: Item) -> dict:
    """Convierte una convocatoria llegada por RSS al mismo shape del catálogo."""
    return {
        "id": item.id,
        "name": item.title,
        # El nombre de la fuente no es el de quien convoca — GFMD solo
        # recopila. Poner "GFMD" acá haría que la tarjeta lo anuncie como si
        # financiara; el origen se indica aparte, en la nota al pie.
        "org": None,
        "url": item.link,
        "url_es": None,
        "kind": "fondo",
        "language": item.language,
        "region": item.region,
        "deadline": item.deadline,
        "deadline_note": None if item.deadline else "Fecha límite en la convocatoria",
        "summary": item.summary,
        "origin": "rss",
        "published": item.published,
        "verified": None,
    }


def build_opportunities(auto_items: list[Item]) -> dict:
    """Mezcla el catálogo curado con las convocatorias llegadas por RSS.

    El estado (abierta / cerrada / permanente) y el orden los calcula el sitio
    en el navegador a partir del deadline, no este script: así una fecha no
    queda desfasada entre las dos corridas diarias del workflow.
    """
    curated, resources = load_catalog()
    curated_urls = {canonicalize_link(e["url"]) for e in curated}
    # GFMD también reseña convocatorias de organizaciones que ya están en el
    # catálogo (FIJ, por ejemplo), con su propia URL. Se descarta la reseña: la
    # entrada curada apunta al sitio de la organización, que lista todos sus
    # ciclos y no solo el que GFMD alcanzó a publicar.
    curated_orgs = {
        (e.get("org") or "").lower() for e in curated if len(e.get("org") or "") > 12
    }

    auto = []
    dropped_regions: list[str] = []
    for item in sorted(auto_items, key=lambda i: i.published_ts, reverse=True):
        if canonicalize_link(item.link) in curated_urls:
            continue
        title = item.title.lower()
        if any(org in title for org in curated_orgs):
            continue
        # Sin región declarada se conserva: no poder determinarla no es razón
        # para esconder una convocatoria que quizá sí aplica.
        if item.region and not AMERICAS_REGION.search(item.region):
            dropped_regions.append(f"{item.region} — {item.title[:60]}")
            continue
        auto.append(opportunity_item_to_dict(item))

    if dropped_regions:
        print(f"  {len(dropped_regions)} convocatorias descartadas por región:")
        for entry in dropped_regions:
            print(f"    - {entry}")

    return {
        "opportunities": [catalog_entry_to_dict(e) for e in curated] + auto,
        "resources": [catalog_entry_to_dict(e) for e in resources],
    }


def item_to_dict(item: Item) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "link": item.link,
        "published": item.published,
        "summary": item.summary,
        "source": item.source,
        "source_id": item.source_id,
        "language": item.language,
        "country": item.country,
        "category": item.category,
        "topics": item.topics,
        "tags": item.tags,
        "also_reported_by": item.also_reported_by,
    }


def main() -> int:
    sources = load_sources()
    all_items: list[Item] = []
    status_entries = []

    for source in sources:
        items, status = fetch_source(source)
        all_items.extend(items)
        status_entries.append(status)

    # Las convocatorias salen del pipeline de noticias antes del dedupe: no se
    # ordenan por fecha de publicación ni caducan a los 90 días como un caso de
    # ataque a la prensa, sino por fecha límite. Ver build_opportunities().
    opportunity_items = [i for i in all_items if i.category == OPPORTUNITY_CATEGORY]
    all_items = [i for i in all_items if i.category != OPPORTUNITY_CATEGORY]

    # Red de arrastre geográfica sobre Google Alerts: sus consultas incluyen
    # "Latin America", pero Google lo trata como sugerencia y deja pasar notas
    # de Medio Oriente, Asia o España. Solo se descarta cuando el item nombra
    # otra región y ninguna de las Américas — si menciona ambas, se conserva.
    kept, dropped_geo, dropped_social = [], [], []
    for item in all_items:
        text = f"{item.title} {item.summary}"
        is_alert = item.priority == GOOGLE_ALERTS_PRIORITY
        if is_alert and is_social_link(item.link):
            dropped_social.append(f"{item.source} — {item.title[:70]}")
        elif (
            is_alert
            and NON_AMERICAS.search(text)
            and not AMERICAS_NEWS.search(text)
        ):
            dropped_geo.append(f"{item.source} — {item.title[:70]}")
        else:
            kept.append(item)
    all_items = kept

    all_items = dedupe_exact(all_items)
    all_items = dedupe_fuzzy(all_items)

    # JSK y cualquier otra fuente marcada no_expira publican por temporada: con
    # el corte parejo su pestaña se vaciaría sola entre ciclos. Su archivo se
    # conserva; el resto sí caduca a los MAX_AGE_DAYS.
    cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=MAX_AGE_DAYS)).timestamp()
    all_items = [
        item for item in all_items if item.no_expira or item.published_ts >= cutoff
    ]
    all_items.sort(key=lambda i: i.published_ts, reverse=True)
    all_items = all_items[:MAX_ITEMS]

    now_iso = datetime.now(tz=timezone.utc).isoformat()

    FEED_OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with FEED_OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "generated_at": now_iso,
                "count": len(all_items),
                "items": [item_to_dict(item) for item in all_items],
            },
            f,
            ensure_ascii=False,
            indent=1,
        )

    opportunities = build_opportunities(opportunity_items)
    with OPPS_OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump({"generated_at": now_iso, **opportunities}, f, ensure_ascii=False, indent=1)

    with STATUS_OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump({"last_run": now_iso, "sources": status_entries}, f, ensure_ascii=False, indent=1)

    active_ok = [s for s in status_entries if s["ok"]]
    if sources and not active_ok:
        print("ERROR: all active sources failed", file=sys.stderr)
        return 1

    if dropped_geo:
        print(f"{len(dropped_geo)} items de alertas descartados por geografía:")
        for entry in dropped_geo:
            print(f"  - {entry}")

    if dropped_social:
        print(f"{len(dropped_social)} items de alertas descartados por ser de redes:")
        for entry in dropped_social:
            print(f"  - {entry}")

    print(f"Wrote {len(all_items)} items from {len(active_ok)}/{len(sources)} sources.")
    print(
        f"Wrote {len(opportunities['opportunities'])} opportunities "
        f"and {len(opportunities['resources'])} resources."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
