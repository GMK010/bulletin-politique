#!/usr/bin/env python3
"""
Bulletin — tableau de bord politique français.

Ce script :
1. va chercher les dernières actus politique (RSS Le Monde / France Info / Le Figaro)
2. va chercher les derniers scrutins (votes) à l'Assemblée nationale (API NosDéputés.fr)
3. génère un site statique (site/index.html) prêt à être publié sur GitHub Pages

Il est pensé pour tourner seul, chaque matin, via une GitHub Action.
Si une source est indisponible, la section correspondante affiche un message
plutôt que de faire échouer tout le site.
"""

import html
import json
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import requests

PARIS_TZ = timezone.utc  # affiché en UTC + note ; évite une dépendance zoneinfo externe
USER_AGENT = "Mozilla/5.0 (compatible; BulletinPolitiqueFR/1.0; usage personnel non commercial)"

RSS_SOURCES = [
    ("Le Monde", "https://www.lemonde.fr/politique/rss_full.xml"),
    ("France Info", "https://www.francetvinfo.fr/politique.rss"),
    ("Le Figaro", "https://www.lefigaro.fr/rss/figaro_politique.xml"),
]

# La numérotation de législature change après chaque élection législative.
# On essaie la plus récente d'abord, puis on retombe sur la précédente si vide.
NOSDEPUTES_LEGISLATURES = [17, 16]


def safe_get(url, timeout=15):
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        return r
    except Exception as e:
        print(f"[warn] échec requête {url} : {e}")
        return None


def fetch_news(max_items=12):
    """Récupère les derniers titres politique depuis plusieurs flux RSS."""
    items = []
    for source_name, url in RSS_SOURCES:
        resp = safe_get(url)
        if resp is None:
            continue
        try:
            feed = feedparser.parse(resp.content)
        except Exception as e:
            print(f"[warn] parsing RSS {source_name} : {e}")
            continue
        for entry in feed.entries[:8]:
            title = html.unescape(getattr(entry, "title", "").strip())
            link = getattr(entry, "link", "")
            published = None
            if getattr(entry, "published", None):
                try:
                    published = parsedate_to_datetime(entry.published)
                except Exception:
                    published = None
            if not title or not link:
                continue
            items.append({
                "source": source_name,
                "title": title,
                "link": link,
                "published": published,
            })
    # Tri par date décroissante (les items sans date passent en dernier)
    items.sort(key=lambda x: x["published"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    # Dédoublonnage grossier par titre
    seen = set()
    deduped = []
    for it in items:
        key = it["title"].lower()[:60]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(it)
    return deduped[:max_items]


def fetch_scrutins(max_items=8):
    """Récupère les derniers scrutins publics (votes) à l'Assemblée nationale
    via l'API JSON de NosDéputés.fr (Regards Citoyens)."""
    for legislature in NOSDEPUTES_LEGISLATURES:
        url = f"https://www.nosdeputes.fr/{legislature}/scrutins/json"
        resp = safe_get(url, timeout=25)
        if resp is None:
            continue
        try:
            data = resp.json()
        except Exception as e:
            print(f"[warn] parsing JSON scrutins (législature {legislature}) : {e}")
            continue
        scrutins = data.get("scrutins") or data.get("scrutin") or []
        if not scrutins:
            continue
        # Les entrées peuvent être {"scrutin": {...}} selon le point d'accès
        normalized = []
        for s in scrutins:
            s = s.get("scrutin", s)
            try:
                normalized.append({
                    "numero": s.get("numero"),
                    "titre": html.unescape(s.get("titre", "") or ""),
                    "date": s.get("date"),
                    "sort": s.get("sort", ""),
                    "pour": int(s.get("nombre_pours", 0) or 0),
                    "contre": int(s.get("nombre_contres", 0) or 0),
                    "abstention": int(s.get("nombre_abstentions", 0) or 0),
                    "legislature": legislature,
                })
            except Exception:
                continue
        normalized.sort(key=lambda x: (x["date"] or ""), reverse=True)
        if normalized:
            return normalized[:max_items]
    return []


def esc(s):
    return html.escape(s or "", quote=True)


def hemicycle_svg(pour, contre, abstention):
    """Petite visualisation en éventail façon hémicycle : chaque vote = un point."""
    total = max(pour + contre + abstention, 1)
    dots = (
        [("#2C4A6E", "pour")] * pour
        + [("#8B2E3C", "contre")] * contre
        + [("#9B9686", "abst.")] * abstention
    )
    n = len(dots)
    width, height = 260, 130
    cx, cy = width / 2, height - 6
    radius = height - 20
    svg_dots = []
    for i, (color, _label) in enumerate(dots):
        # Répartit les points en éventail, de gauche à droite, sur un demi-cercle
        t = i / max(n - 1, 1)  # 0..1
        x = cx + radius * (0.92 * (2 * t - 1))
        y = cy - radius * (1 - abs(2 * t - 1) ** 1.15) * 0.92
        svg_dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.1" fill="{color}" opacity="0.92"/>')
    return (
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'role="img" aria-label="Répartition du vote : {pour} pour, {contre} contre, {abstention} abstentions">'
        + "".join(svg_dots)
        + "</svg>"
    )


def render_news_section(items):
    if not items:
        return '<p class="empty">Actualités indisponibles pour le moment — les flux RSS n\'ont pas répondu.</p>'
    rows = []
    for it in items:
        date_txt = ""
        if it["published"]:
            date_txt = it["published"].astimezone(timezone.utc).strftime("%d/%m à %Hh%M")
        rows.append(f'''
        <li class="news-item">
          <a href="{esc(it['link'])}" target="_blank" rel="noopener">{esc(it['title'])}</a>
          <span class="news-meta">{esc(it['source'])}{' · ' + date_txt if date_txt else ''}</span>
        </li>''')
    return f'<ul class="news-list">{"".join(rows)}</ul>'


def render_scrutins_section(scrutins):
    if not scrutins:
        return '<p class="empty">Votes indisponibles pour le moment — l\'API NosDéputés.fr n\'a pas répondu.</p>'
    cards = []
    for s in scrutins:
        date_txt = s["date"] or ""
        sort_txt = esc(s["sort"] or "—")
        titre = esc(s["titre"]) or "Scrutin sans titre"
        cards.append(f'''
        <article class="vote-card">
          <div class="vote-card-head">
            <span class="vote-num">Scrutin n°{esc(str(s['numero']))}</span>
            <span class="vote-date">{esc(date_txt)}</span>
          </div>
          <h3 class="vote-title">{titre}</h3>
          <div class="vote-body">
            {hemicycle_svg(s['pour'], s['contre'], s['abstention'])}
            <dl class="vote-tally">
              <div><dt>Résultat</dt><dd class="vote-sort">{sort_txt}</dd></div>
              <div><dt>Pour</dt><dd>{s['pour']}</dd></div>
              <div><dt>Contre</dt><dd>{s['contre']}</dd></div>
              <div><dt>Abst.</dt><dd>{s['abstention']}</dd></div>
            </dl>
          </div>
        </article>''')
    return f'<div class="vote-grid">{"".join(cards)}</div>'


POLL_TRACKERS = [
    ("Popularité présidentielle — IFOP", "https://www.ifop.com/tag/barometre-politique/"),
    ("Baromètre Elabe / Les Échos", "https://elabe.fr/thematique/politique/"),
    ("Sondages Ipsos", "https://www.ipsos.com/fr-fr/sondages-et-etudes-politiques"),
    ("Agrégateur — NSPPolls (GitHub)", "https://github.com/nsppolls/nsppolls"),
]


def render_polls_section():
    cards = "".join(
        f'''<a class="poll-card" href="{esc(url)}" target="_blank" rel="noopener">
              <span class="poll-name">{esc(name)}</span>
              <span class="poll-arrow">→</span>
            </a>'''
        for name, url in POLL_TRACKERS
    )
    return f'''
    <p class="empty" style="margin-bottom:1rem">
      Pas d'API publique et gratuite fiable pour les chiffres de sondages :
      voici les trackers officiels à consulter directement.
    </p>
    <div class="poll-grid">{cards}</div>
    '''


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bulletin — suivi politique français</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,500;8..60,600&family=IBM+Plex+Sans:wght@400;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="style.css">
</head>
<body>
  <header class="masthead">
    <div class="masthead-inner">
      <span class="eyebrow">Édition quotidienne</span>
      <h1>Bulletin</h1>
      <p class="subtitle">Actualité, Assemblée nationale &amp; sondages — France</p>
      <p class="updated-at">Généré le {generated_at} (heure UTC)</p>
    </div>
  </header>

  <main>
    <section class="section">
      <h2><span class="section-num">01</span> À la une</h2>
      {news_html}
    </section>

    <section class="section">
      <h2><span class="section-num">02</span> Assemblée nationale — derniers scrutins</h2>
      {scrutins_html}
    </section>

    <section class="section">
      <h2><span class="section-num">03</span> Sondages</h2>
      {polls_html}
    </section>
  </main>

  <footer class="site-footer">
    <p>Sources : Le Monde, France Info, Le Figaro (flux RSS) · NosDéputés.fr — Regards Citoyens (Licence ouverte / Open Licence)
    pour les données de vote de l'Assemblée nationale · Générée automatiquement, sans intervention manuelle.</p>
  </footer>
</body>
</html>
"""


def build():
    news = fetch_news()
    scrutins = fetch_scrutins()

    html_out = HTML_TEMPLATE.format(
        generated_at=datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M"),
        news_html=render_news_section(news),
        scrutins_html=render_scrutins_section(scrutins),
        polls_html=render_polls_section(),
    )

    with open("site/index.html", "w", encoding="utf-8") as f:
        f.write(html_out)

    print(f"[ok] {len(news)} actus, {len(scrutins)} scrutins récupérés. site/index.html écrit.")


if __name__ == "__main__":
    build()
