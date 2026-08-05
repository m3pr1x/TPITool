# Outil de plan de chargement et d'empotage

De la packing list au plan 3D, avec une étape de vérification humaine au milieu.

Import d'un fichier de colisage (Excel, PDF, CSV) → contrôle et complétion par l'équipe →
placement 3D sous contraintes → plan réagençable à la souris → export.

**Essayer sans rien préparer :** sur l'écran d'import, le lien *Essayer avec une packing
list d'exemple* charge un fichier fictif de 22 colis, dont deux hors gabarit.

## Démarrer

Double-clique **`demarrer.command`**. La première fois, il installe les dépendances
(une minute), puis ouvre <http://127.0.0.1:8000> tout seul.

En ligne de commande :

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python -m uvicorn app:app --port 8000
```

Rien ne sort de la machine : le fichier est lu en mémoire, calculé en local, et la
session disparaît à l'arrêt du serveur.

## Le parcours en quatre étapes

**1 · Import** — `.xls`, `.xlsx`, `.pdf`, `.csv`.
Le PDF est découpé en colonnes par détection des gouttières blanches, mesurées sur
les seules lignes de données : les titres et les en-têtes s'étalent en travers et
boucheraient les blancs. C'est ce qui permet de lire `4 150 4 776 351 265 240` là où
l'extraction de texte brut est inexploitable.

**2 · Colonnes** — l'outil propose une ligne d'en-tête et une affectation de colonnes,
**tu valides ou tu corriges**. C'est délibéré : sur les fichiers de référence qui ont servi
à régler l'outil, deux classeurs issus du **même modèle d'entreprise** n'avaient pas les mêmes
indices de colonnes — une colonne vide insérée en tête décalait toute la grille. Un lecteur
écrit en dur sur les indices renvoie zéro ligne sur l'un des deux.

**3 · Vérification** — le cœur de l'outil.
- Contrôles automatiques : volume déclaré contre L×l×h, densité aberrante, poids net
  supérieur au brut, poids manquant, références en doublon, cotes toutes rondes
  (marquées « estimé »).
- Réconciliation avec la ligne TOTAL du document — elle attrape les erreurs de
  **lecture**. Les contrôles ligne à ligne attrapent les erreurs de **saisie** : sur le
  fichier de référence, deux caisses aux cotes strictement identiques étaient déclarées
  0,5 et 0,2 m³ — et le total du document était cohérent avec la valeur fausse.
- **Saisie métier** : gerbabilité, charge admissible sur le dessus, rotation autorisée,
  maintien au sol, statut estimé/confirmé. Édition unitaire ou par sélection multiple.

**4 · Plan 3D** — placement automatique, puis vue 3D temps réel (WebGL 2, sans
bibliothèque externe) : orbite à la souris, molette pour zoomer, `⇧` + glisser pour
déplacer la vue, vues préréglées 3/4 · dessus · côté · portes.

Les colis hors gabarit sortent dans un tableau à part avec la solution proposée
(flat rack, open top, conventionnel) et le motif.

### Réagencer à la main

Coche **Mode édition**, puis clique une caisse :

| Geste | Effet |
|---|---|
| glisser | déplace la caisse dans le plan horizontal, à sa hauteur actuelle |
| `←` `↑` `→` `↓` | 1 cm — avec `⇧`, 10 cm |
| `R` ou *Pivoter 90°* | fait pivoter la caisse autour de l'axe vertical |
| `Esc` | désélectionne |
| clic sur une ligne du tableau | sélectionne la caisse correspondante |

Chaque déplacement est validé en temps réel : pas de chevauchement, pas de sortie du
conteneur, et au moins 70 % de la base en appui si la caisse n'est pas au sol. Une
position impossible s'affiche en rouge et la caisse revient à sa place.

Le plan modifié est conservé dans l'export CSV ; *Annuler mes déplacements* rétablit le
calcul d'origine, *Recalculer* l'écrase. Les charges cumulées affichées restent celles du
calcul automatique — elles ne sont pas recalculées après un déplacement manuel.

## La gerbabilité

C'est le réglage qui pèse le plus lourd, et il n'est renseigné dans aucune des trois
packing lists de référence. Sur un projet réel de 128 colis conteneurisables :

| Gerbabilité | Unités | Remplissage moyen |
|---|---|---|
| non gerbable | 16 × 40'HC | 45,7 % |
| gerbable | 10 × 40'HC | 73,1 % |

Six conteneurs d'écart, environ 27 000 $ sur une seule expédition. D'où le défaut
volontairement **prudent** (non gerbable) : l'erreur coûte de l'argent, pas de la casse.

## Le moteur

Points extrêmes + insertion first-fit par volume décroissant, rotation autour de l'axe
vertical uniquement. Contraintes appliquées :

- appui minimum de 70 % de la base sur du solide ;
- gerbabilité du support (`non` / `oui` / `sur empreinte identique`) ;
- charge admissible cumulée, propagée le long de la pile jusqu'au sol ;
- charge utile de l'unité ;
- plafond de remplissage ferme — un plan à 95 % n'est pas arrimable, le Code CTU impose
  de reprendre 0,8 g vers l'avant et 0,5 g latéralement, donc il faut les vides de calage ;
- marge de calage soustraite des dimensions internes.

Si plusieurs types d'unités sont autorisés, chaque unité est redescendue sur le plus
petit format qui contient encore tout son chargement.

## Fichiers

| Fichier | Rôle |
|---|---|
| `app.py` | serveur FastAPI et points d'entrée JSON |
| `ingest.py` | lecture xls/xlsx/pdf/csv, détection de structure, contrôles |
| `gabarit.py` | référentiel des unités et classification conforme / limite / hors gabarit |
| `packer.py` | moteur de placement 3D |
| `static/index.html` | interface complète, sans dépendance externe |
| `static/viewer.js` | moteur 3D WebGL 2 : caméra, rendu, sélection, déplacement |

## Ce que la v1 ne fait pas

Répartition de charge à l'essieu, séquence de déchargement imposée, ségrégation IMDG,
optimisation du regroupement d'expéditions, OCR des PDF scannés, export PDF mis en page,
persistance entre deux sessions, recalcul des charges après déplacement manuel. Le calcul par n° d'expédition existe déjà et montre
l'ampleur du sujet : sur ce même projet, 10 conteneurs en lot unique contre 25 en respectant
les 19 expéditions inscrites dans le document.

## Mettre l'outil en ligne

L'application a un **backend Python** : elle lit des `.xls`, `.xlsx` et des PDF, et fait
tourner un moteur de placement 3D côté serveur. **GitHub Pages ne peut donc pas
l'héberger** — Pages ne sert que des fichiers statiques. Il faut un hébergeur qui exécute
du Python. Le dépôt contient déjà tout le nécessaire.

### Option 1 — Render, gratuit, ~5 minutes

1. Crée un compte sur <https://render.com> et connecte ton compte GitHub.
2. **New +** → **Blueprint** → choisis ce dépôt. Render lit `render.yaml` tout seul.
3. Valide. Au bout de deux ou trois minutes tu obtiens une adresse du type
   `https://tpitool.onrender.com`.
4. Le mot de passe d'accès est généré automatiquement : onglet **Environment** du service,
   variable `TPITOOL_MDP`. Le navigateur le demandera à l'ouverture (identifiant : ce que
   tu veux, mot de passe : cette valeur).

Sur l'offre gratuite le service s'endort après 15 minutes sans visite ; la première
ouverture suivante prend une trentaine de secondes. Pour un lien de démonstration c'est
sans importance.

### Option 2 — un lien tout de suite, sans rien déployer

Si l'outil tourne déjà sur ton Mac, un tunnel suffit :

```bash
brew install cloudflared
cloudflared tunnel --url http://localhost:8000
```

Cloudflare affiche une adresse `https://…trycloudflare.com` utilisable immédiatement par
qui tu veux. Elle vit tant que la commande tourne. Utile pour faire essayer quelqu'un dans
l'heure ; à ne pas laisser ouvert sans avoir défini `TPITOOL_MDP` :

```bash
TPITOOL_MDP="un-mot-de-passe" ./demarrer.command
```

### Option 3 — Docker, partout ailleurs

Le `Dockerfile` fonctionne tel quel sur Fly.io, Hugging Face Spaces, Scalingo, Clever Cloud
ou un VPS :

```bash
docker build -t tpitool .
docker run -p 8000:8000 -e TPITOOL_MDP=secret tpitool
```

### Avant d'ouvrir le lien à d'autres

- **Mets `TPITOOL_MDP`.** Sans mot de passe, n'importe qui peut déposer des fichiers sur
  ton instance.
- Les fichiers importés ne sont **jamais écrits sur disque** : ils restent en mémoire le
  temps de la session, purgée après une heure d'inactivité, et vingt sessions au maximum
  sont conservées.
- La taille d'import est plafonnée à 30 Mo (`TPITOOL_MAX_MO` pour la changer).
- **Ce dépôt est public.** Aucune packing list réelle n'y figure : le `.gitignore` exclut
  les `.xls`, `.xlsx` et `.pdf`, sauf l'exemple fictif. Garde cette règle — les packing
  lists contiennent des noms, des courriels et des téléphones de personnes réelles.

## Référentiel des unités

Dimensions **internes** en centimètres, dans `gabarit.py`. Conteneurs d'après CMA CGM,
tautliner d'après la spécification standard. À ajuster selon les équipements réellement
proposés par vos armateurs.
