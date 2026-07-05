# Bulletin — suivi politique français

Site statique qui se régénère **tout seul chaque matin** (~8h à Paris) avec :
- les derniers titres politique (Le Monde, France Info, Le Figaro),
- les derniers scrutins (votes) à l'Assemblée nationale (source : NosDéputés.fr / Regards Citoyens),
- des liens directs vers les trackers de sondages officiels (IFOP, Elabe, Ipsos) — voir la
  limite expliquée plus bas.

## Mise en ligne (10 minutes, une seule fois)

1. **Crée un nouveau dépôt** sur GitHub (public ou privé), par exemple `bulletin-politique`.
2. **Pousse ces fichiers** dans ce dépôt :
   ```bash
   cd politique-dashboard
   git init
   git add .
   git commit -m "Premier envoi du bulletin"
   git branch -M main
   git remote add origin https://github.com/TON-PSEUDO/bulletin-politique.git
   git push -u origin main
   ```
3. Dans le dépôt sur GitHub : **Settings → Pages → Build and deployment → Source**,
   choisis **GitHub Actions** (pas "Deploy from a branch").
4. Va dans l'onglet **Actions** du dépôt, ouvre le workflow *"Mise à jour quotidienne du
   bulletin"* et clique **Run workflow** pour le lancer une première fois manuellement.
5. Une fois le workflow terminé (icône verte), ton site est en ligne à l'adresse indiquée
   dans **Settings → Pages** (généralement `https://TON-PSEUDO.github.io/bulletin-politique/`).

À partir de là, plus rien à faire : la GitHub Action se relance seule chaque matin et
republie le site avec les données fraîches.

## Tester en local avant de pousser

```bash
pip install -r requirements.txt
python fetch_and_build.py
# ouvre ensuite site/index.html dans un navigateur
```

## Limites à connaître

- **Horaire exact** : le cron GitHub Actions est en UTC et ne suit pas l'heure d'été/hiver
  française. Le fichier `.github/workflows/daily.yml` est réglé sur 6h UTC, ce qui donne
  8h à Paris en hiver et 7h en été (heure d'été : dernier dimanche de mars → dernier
  dimanche d'octobre). Ajuste l'heure du cron directement dans ce fichier si besoin —
  GitHub Actions peut aussi retarder légèrement l'exécution en cas de forte charge.
- **Sondages** : il n'existe pas d'API publique, gratuite et fiable qui donne les chiffres
  de popularité/intentions de vote en direct (IFOP, Ipsos, Elabe etc. ne publient pas de
  flux exploitable automatiquement). Plutôt que d'afficher des chiffres scrapés qui
  cassent au premier changement de mise en page du site source, le bulletin pointe
  directement vers les trackers officiels. Si tu veux aller plus loin, le projet open
  source [nsppolls](https://github.com/nsppolls/nsppolls) republie un historique de
  sondages présidentielle en CSV/JSON — on peut l'intégrer dans une V2.
- **Législature Assemblée nationale** : le script essaie la 17e législature puis retombe
  sur la 16e si l'API ne répond pas. À ajuster dans `NOSDEPUTES_LEGISLATURES` en haut de
  `fetch_and_build.py` après la prochaine élection législative.
- Les flux RSS (Le Monde, France Info, Le Figaro) et l'API NosDéputés.fr sont des
  services tiers gratuits mais non contractuels : ils peuvent changer d'adresse ou tomber
  en panne. Le script est écrit pour afficher un message plutôt que planter si une
  source ne répond pas.

## Pour aller plus loin

- Ajouter d'autres flux RSS dans `RSS_SOURCES` (`fetch_and_build.py`).
- Ajouter une section "Sénat" via l'API équivalente `nossenateurs.fr`.
- Filtrer les scrutins par thème (économie, immigration...) via les mots-clés du titre.
- Ajouter un historique en gardant les anciennes éditions (`site/archives/2026-07-05.html`).

## Attribution

Données de vote : NosDéputés.fr par Regards Citoyens, à partir des données de
l'Assemblée nationale (Licence ouverte / Open Licence). Merci de conserver cette mention
si tu republies ou modifies ces données.
