#!/usr/bin/env python3
"""
Bulletin — tableau de bord politique français.

Ce script :
1. va chercher les dernières actus politique (RSS Le Monde / France Info / Le Figaro)
2. va chercher les derniers scrutins (votes) à l'Assemblée nationale (API NosDéputés.fr)
3. décrit les 11 groupes politiques de l'Assemblée nationale (données statiques, curées)
4. génère un site statique (site/index.html) prêt à être publié sur GitHub Pages,
   organisé en onglets, pensé pour être compris en un coup d'œil.

Il est pensé pour tourner seul, chaque matin, via une GitHub Action.
Si une source est indisponible, la section correspondante affiche un message
plutôt que de faire échouer tout le site.
"""

import html
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import requests

USER_AGENT = "Mozilla/5.0 (compatible; BulletinPolitiqueFR/1.0; usage personnel non commercial)"

RSS_SOURCES = [
    ("Le Monde", "https://www.lemonde.fr/politique/rss_full.xml"),
    ("France Info", "https://www.francetvinfo.fr/politique.rss"),
    ("Le Figaro", "https://www.lefigaro.fr/rss/figaro_politique.xml"),
]

# La numérotation de législature change après chaque élection législative.
# On essaie la plus récente d'abord, puis on retombe sur la précédente si vide.
NOSDEPUTES_LEGISLATURES = [17, 16]
CURRENT_LEGISLATURE = 17

# --------------------------------------------------------------------------
# Les 11 groupes politiques de l'Assemblée nationale (17e législature).
# Données curées à la main (chef·fe de groupe, couleur, description simple,
# effectif approximatif) — l'effectif exact bouge un peu chaque mois, un lien
# vers Datan est fourni sur chaque carte pour vérifier le chiffre du jour.
# "position" va de 0 (extrême gauche) à 10 (extrême droite), juste pour placer
# un repère visuel sur une frise — ce n'est pas une science exacte.
# --------------------------------------------------------------------------
PARTIES = [
    {
        "sigle": "LFI-NFP", "nom": "La France insoumise",
        "couleur": "#CC2443", "position": 0.3, "chef": "Mathilde Panot",
        "resume": "Ils veulent que l'État aide beaucoup plus les gens qui ont peu d'argent, et augmente les impôts des plus riches et des grandes entreprises.",
        "sieges_approx": 70, "aliases": ["LFI-NFP", "LFI-NUPES", "LFI", "FI"],
    },
    {
        "sigle": "GDR", "nom": "Gauche Démocrate et Républicaine (communistes)",
        "couleur": "#B22222", "position": 1.2, "chef": "Stéphane Peu",
        "resume": "Historiquement liés au Parti communiste, ils défendent les services publics et les ouvriers face aux grandes entreprises.",
        "sieges_approx": 17, "aliases": ["GDR", "GDR-NUPES"],
    },
    {
        "sigle": "EcoS", "nom": "Écologiste et Social",
        "couleur": "#2E8B57", "position": 2.2, "chef": "Cyrielle Chatelain",
        "resume": "Leur priorité, c'est protéger la nature et le climat, tout en réduisant les inégalités entre les gens.",
        "sieges_approx": 38, "aliases": ["ECOS", "ECOLO", "ECOLO-NUPES", "ECO"],
    },
    {
        "sigle": "SOC", "nom": "Socialistes et apparentés",
        "couleur": "#FF8080", "position": 2.8, "chef": "Boris Vallaud",
        "resume": "Le parti socialiste veut un État qui protège et redistribue, avec plus de justice sociale.",
        "sieges_approx": 66, "aliases": ["SOC"],
    },
    {
        "sigle": "EPR", "nom": "Ensemble pour la République",
        "couleur": "#FFD966", "position": 5.0, "chef": "Gabriel Attal",
        "resume": "Issu du camp du président Emmanuel Macron. Ils veulent réformer sans aller trop à gauche ni trop à droite.",
        "sieges_approx": 78, "aliases": ["EPR", "REN", "RE"],
    },
    {
        "sigle": "Dem", "nom": "Les Démocrates (MoDem)",
        "couleur": "#FFA500", "position": 5.3, "chef": "Marc Fesneau",
        "resume": "Un parti du centre, allié du gouvernement, qui cherche le compromis entre la gauche et la droite.",
        "sieges_approx": 35, "aliases": ["DEM", "MODEM"],
    },
    {
        "sigle": "HOR", "nom": "Horizons & Indépendants",
        "couleur": "#66C2CC", "position": 5.6, "chef": "Paul Christophe",
        "resume": "Fondé par Édouard Philippe, ce parti du centre soutient aussi le gouvernement actuel.",
        "sieges_approx": 30, "aliases": ["HOR"],
    },
    {
        "sigle": "LIOT", "nom": "Libertés, Indépendants, Outre-mer et Territoires",
        "couleur": "#B7A57A", "position": 5.8, "chef": "Laurent Panifous",
        "resume": "Un groupe d'élus indépendants, souvent issus des territoires d'outre-mer, qui votent au cas par cas.",
        "sieges_approx": 22, "aliases": ["LIOT"],
    },
    {
        "sigle": "DR", "nom": "Droite Républicaine (ex-Les Républicains)",
        "couleur": "#3366CC", "position": 7.2, "chef": "Laurent Wauquiez",
        "resume": "Le parti Les Républicains veut moins de dépenses publiques et des règles plus strictes sur la sécurité et l'immigration.",
        "sieges_approx": 48, "aliases": ["DR", "LR"],
    },
    {
        "sigle": "UDR", "nom": "Union des droites pour la République",
        "couleur": "#001F5B", "position": 8.6, "chef": "Éric Ciotti",
        "resume": "Un petit groupe de droite, allié du Rassemblement national, sur une ligne très proche de lui.",
        "sieges_approx": 16, "aliases": ["UDR", "AD", "A DROITE"],
    },
    {
        "sigle": "RN", "nom": "Rassemblement National",
        "couleur": "#0D3B66", "position": 9.6, "chef": "Marine Le Pen",
        "resume": "Le plus grand groupe de l'Assemblée. Ils veulent moins d'immigration et donner la priorité aux Français dans plusieurs domaines.",
        "sieges_approx": 120, "aliases": ["RN"],
    },
]


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
            summary_raw = getattr(entry, "summary", "") or getattr(entry, "description", "")
            summary = html.unescape(re.sub(r"<[^>]+>", "", summary_raw)).strip()
            if len(summary) > 180:
                summary = summary[:177].rsplit(" ", 1)[0] + "…"
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
                "summary": summary,
                "published": published,
            })
    items.sort(key=lambda x: x["published"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
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
        normalized = []
        for s in scrutins:
            s = s.get("scrutin", s)
            try:
                normalized.append({
                    "numero": s.get("numero"),
                    "titre": html.unescape(s.get("titre", "") or ""),
                    "date": s.get("date"),
                    "sort": (s.get("sort", "") or "").strip(),
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


def fetch_live_seat_counts():
    """Compte, pour chaque groupe politique, le nombre de député·es actuellement
    en mandat, à partir de la liste complète des député·es de NosDéputés.fr.
    Renvoie un dict {SIGLE_EN_MAJUSCULES: nombre}, ou {} si la source ne répond
    pas / a un format inattendu (dans ce cas on retombe sur les chiffres
    approximatifs figés dans PARTIES)."""
    url = "https://www.nosdeputes.fr/deputes/enmandat/json"
    resp = safe_get(url, timeout=25)
    if resp is None:
        return {}
    try:
        data = resp.json()
    except Exception as e:
        print(f"[warn] parsing JSON députés : {e}")
        return {}

    deputes = data.get("deputes") or data.get("depute") or []
    counts = {}
    for d in deputes:
        d = d.get("depute", d)
        sigle = (
            d.get("groupe_sigle")
            or d.get("groupe_acronyme")
            or d.get("groupe")
            or ""
        )
        sigle = str(sigle).strip().upper()
        if not sigle:
            continue
        counts[sigle] = counts.get(sigle, 0) + 1

    if not counts:
        print("[warn] liste des députés récupérée mais aucun champ de groupe reconnu")
    return counts


def resolve_seat_count(party, live_counts):
    """Cherche le nombre réel de député·es du groupe via ses alias ; à défaut,
    retombe sur l'estimation figée dans PARTIES."""
    for alias in party.get("aliases", [party["sigle"]]):
        n = live_counts.get(alias.upper())
        if n:
            return n, True  # (effectif, est_a_jour)
    return party["sieges_approx"], False


def esc(s):
    return html.escape(s or "", quote=True)


# --------------------------------------------------------------------------
# Rendu HTML de chaque onglet
# --------------------------------------------------------------------------

def render_news_section(items):
    if not items:
        return '<p class="empty">Actualités indisponibles pour le moment — les flux RSS n\'ont pas répondu.</p>'
    rows = []
    for it in items:
        date_txt = ""
        if it["published"]:
            date_txt = it["published"].astimezone(timezone.utc).strftime("%d/%m à %Hh%M")
        summary_html = f'<p class="news-summary">{esc(it["summary"])}</p>' if it.get("summary") else ""
        rows.append(f'''
        <li class="news-item">
          <a class="news-title" href="{esc(it['link'])}" target="_blank" rel="noopener">{esc(it['title'])}</a>
          <span class="news-meta">{esc(it['source'])}{' · ' + date_txt if date_txt else ''}</span>
          {summary_html}
          <a class="news-readmore" href="{esc(it['link'])}" target="_blank" rel="noopener">Lire l'article complet →</a>
        </li>''')
    return f'<ul class="news-list">{"".join(rows)}</ul>'


def verdict_badge(sort_txt):
    """Transforme le texte brut du sort en badge simple (✅ / ❌ / ➖)."""
    s = (sort_txt or "").lower()
    if "adopt" in s:
        return "✅", "Adopté", "adopte"
    if "rejet" in s or "non adopt" in s:
        return "❌", "Rejeté", "rejete"
    return "➖", (sort_txt or "Résultat inconnu"), "autre"


def render_scrutins_section(scrutins):
    if not scrutins:
        return '<p class="empty">Votes indisponibles pour le moment — l\'API NosDéputés.fr n\'a pas répondu.</p>'
    cards = []
    for s in scrutins:
        total = max(s["pour"] + s["contre"] + s["abstention"], 1)
        pour_pct = round(100 * s["pour"] / total)
        contre_pct = round(100 * s["contre"] / total)
        abst_pct = max(0, 100 - pour_pct - contre_pct)
        emoji, verdict_txt, verdict_class = verdict_badge(s["sort"])
        titre = esc(s["titre"]) or "Scrutin sans titre"
        detail_url = f"https://www.assemblee-nationale.fr/dyn/{s['legislature']}/scrutins/{s['numero']}"

        def bar(label, emoji_row, count, pct, css_class):
            return f'''
            <div class="vote-row">
              <span class="vote-row-label">{emoji_row} {label}</span>
              <div class="vote-row-bar-track">
                <div class="vote-row-bar-fill {css_class}" style="width:{pct}%"></div>
              </div>
              <span class="vote-row-count">{count} <small>({pct}%)</small></span>
            </div>'''

        cards.append(f'''
        <article class="vote-card">
          <div class="vote-card-head">
            <span class="vote-num">Scrutin n°{esc(str(s['numero']))}</span>
            <span class="vote-date">{esc(s['date'] or '')}</span>
          </div>
          <h3 class="vote-title">{titre}</h3>
          <span class="verdict-badge verdict-{verdict_class}">{emoji} {esc(verdict_txt)}</span>
          <div class="vote-bars">
            {bar("Pour", "👍", s['pour'], pour_pct, "bar-pour")}
            {bar("Contre", "👎", s['contre'], contre_pct, "bar-contre")}
            {bar("Abstention", "🤷", s['abstention'], abst_pct, "bar-abstention")}
          </div>
          <a class="vote-detail-link" href="{esc(detail_url)}" target="_blank" rel="noopener">
            Voir qui a voté quoi, groupe par groupe →
          </a>
        </article>''')
    return f'<div class="vote-grid">{"".join(cards)}</div>'


def render_parties_section(live_counts):
    cards = []
    any_stale = False
    for p in sorted(PARTIES, key=lambda x: x["position"]):
        marker_pct = round(p["position"] / 10 * 100)
        seats, is_live = resolve_seat_count(p, live_counts)
        if not is_live:
            any_stale = True
        seats_note = "" if is_live else " (estimation)"
        cards.append(f'''
        <article class="party-card" style="--party-color:{esc(p['couleur'])}">
          <div class="party-card-top">
            <span class="party-badge">{esc(p['sigle'])}</span>
            <span class="party-seats">🪑 {seats} député·es{esc(seats_note)}</span>
          </div>
          <h3 class="party-name">{esc(p['nom'])}</h3>
          <p class="party-leader">👤 Chef·fe de groupe : <strong>{esc(p['chef'])}</strong></p>
          <div class="party-spectrum" aria-hidden="true">
            <div class="party-spectrum-track"></div>
            <div class="party-spectrum-marker" style="left:{marker_pct}%"></div>
          </div>
          <p class="party-resume">{esc(p['resume'])}</p>
        </article>''')
    legend = '''
    <div class="spectrum-legend">
      <span>← Plutôt à gauche</span>
      <span>Plutôt à droite →</span>
    </div>'''
    if any_stale:
        note = '''
        <p class="empty" style="margin-top:1.2rem">
          Certains effectifs n'ont pas pu être récupérés en direct aujourd'hui — ils affichent
          une estimation. Chiffre exact du jour :
          <a href="https://datan.fr/groupes" target="_blank" rel="noopener">datan.fr/groupes</a>.
        </p>'''
    else:
        note = '''
        <p class="empty" style="margin-top:1.2rem">
          Effectifs récupérés en direct ce matin auprès de NosDéputés.fr.
        </p>'''
    return legend + f'<div class="party-grid">{"".join(cards)}</div>' + note


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
<link href="https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,500;8..60,600&family=IBM+Plex+Sans:wght@400;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
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

  <nav class="tabbar" aria-label="Sections du bulletin">
    <button class="tab-btn active" data-tab="actus" type="button"><span class="tab-icon">📰</span> À la une</button>
    <button class="tab-btn" data-tab="assemblee" type="button"><span class="tab-icon">🏛️</span> Assemblée</button>
    <button class="tab-btn" data-tab="partis" type="button"><span class="tab-icon">🎭</span> Partis</button>
    <button class="tab-btn" data-tab="sondages" type="button"><span class="tab-icon">📊</span> Sondages</button>
  </nav>

  <main>
    <section class="panel" id="panel-actus" data-panel="actus">
      {news_html}
    </section>

    <section class="panel" id="panel-assemblee" data-panel="assemblee" hidden>
      {scrutins_html}
    </section>

    <section class="panel" id="panel-partis" data-panel="partis" hidden>
      {parties_html}
    </section>

    <section class="panel" id="panel-sondages" data-panel="sondages" hidden>
      {polls_html}
    </section>
  </main>

  <footer class="site-footer">
    <p>Sources : Le Monde, France Info, Le Figaro (flux RSS) · NosDéputés.fr — Regards Citoyens (Licence ouverte / Open Licence)
    pour les données de vote de l'Assemblée nationale · Générée automatiquement, sans intervention manuelle.</p>
  </footer>

  <button class="back-to-top" type="button" aria-label="Retour en haut de page" hidden>↑</button>

  <script>
    (function () {{
      var tabs = document.querySelectorAll('.tab-btn');
      var panels = document.querySelectorAll('.panel');
      var backBtn = document.querySelector('.back-to-top');

      function activate(name) {{
        tabs.forEach(function (t) {{ t.classList.toggle('active', t.dataset.tab === name); }});
        panels.forEach(function (p) {{ p.hidden = p.dataset.panel !== name; }});
        window.scrollTo({{ top: 0, behavior: 'instant' in window ? 'instant' : 'auto' }});
      }}

      tabs.forEach(function (t) {{
        t.addEventListener('click', function () {{ activate(t.dataset.tab); }});
      }});

      function onScroll() {{
        if (backBtn) backBtn.hidden = window.scrollY < 500;
      }}
      window.addEventListener('scroll', onScroll, {{ passive: true }});
      if (backBtn) {{
        backBtn.addEventListener('click', function () {{
          window.scrollTo({{ top: 0, behavior: 'smooth' }});
        }});
      }}
    }})();
  </script>
</body>
</html>
"""


def build():
    news = fetch_news()
    scrutins = fetch_scrutins()
    live_counts = fetch_live_seat_counts()

    html_out = HTML_TEMPLATE.format(
        generated_at=datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M"),
        news_html=render_news_section(news),
        scrutins_html=render_scrutins_section(scrutins),
        parties_html=render_parties_section(live_counts),
        polls_html=render_polls_section(),
    )

    with open("site/index.html", "w", encoding="utf-8") as f:
        f.write(html_out)

    print(f"[ok] {len(news)} actus, {len(scrutins)} scrutins, "
          f"{len(live_counts)} groupes en direct. site/index.html écrit.")


if __name__ == "__main__":
    build()
