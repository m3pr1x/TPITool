"""Lecture des packing lists : Excel (.xls / .xlsx), PDF et CSV.

Principe : on ne devine jamais en silence. Chaque fichier est transformé en
grille de cellules brute, l'outil PROPOSE une ligne d'en-tête et une
correspondance de colonnes, et l'utilisateur valide ou corrige avant parsing.
"""

import io
import os
import re
import unicodedata

# ---------------------------------------------------------------- champs cibles

CHAMPS = [
    ("ref",      "N° de colis"),
    ("desc",     "Désignation / contenu"),
    ("qty",      "Quantité"),
    ("length",   "Longueur"),
    ("width",    "Largeur"),
    ("height",   "Hauteur"),
    ("gross",    "Poids brut"),
    ("net",      "Poids net"),
    ("volume",   "Volume déclaré"),
    ("group",    "N° d'expédition / lot"),
    ("supplier", "Fournisseur"),
]

# Libellés reconnus, du plus spécifique au plus générique.
INDICES = {
    "ref":      ["package n", "package no", "n° de colis", "no colis", "case n", "colis n",
                 "package number", "item n", "marks", "pack n"],
    "desc":     ["packing content", "designation", "désignation", "description", "contenu",
                 "commodity", "goods"],
    "qty":      ["quantity", "quantité", "qty", "nombre"],
    "length":   ["length", "longueur", "long."],
    "width":    ["width", "largeur", "larg."],
    "height":   ["height", "hauteur", "haut."],
    "gross":    ["gross weight", "gross", "poids brut", "brut", "g.w"],
    "net":      ["net weight", "net", "poids net", "n.w"],
    "volume":   ["volume", "cbm", "m3", "m³"],
    "group":    ["shipment", "expédition", "expedition", "lot", "envoi"],
    "supplier": ["supplier", "fournisseur", "vendor", "maker"],
}

ANCRE_DIMS = ["measurements", "dimensions", "mesures", "dimension"]


def _norm(s):
    if s is None:
        return ""
    s = str(s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def _nombre(v):
    """Convertit une cellule en float, en tolérant les formats humains."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    for esp in ("\u00a0", "\u202f", "\u2009", "\u2007"):
        s = s.replace(esp, " ")
    # on isole le premier nombre : « 32,18 m3 » ne doit pas devenir 32,183
    m = re.search(r"[-+]?\d[\d .,]*", s)
    if not m:
        return None
    s = re.sub(r"[^\d,.\-+]", "", m.group(0))
    if not s or s in "-+.,":
        return None
    if "," in s and "." in s:
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------- lecture brute

def lire_fichier(chemin, contenu=None):
    """Retourne {"kind":…, "sheets":[{"name":…, "grid":[[str,…],…]}]}"""
    ext = os.path.splitext(chemin)[1].lower()
    if ext == ".xls":
        return _lire_xls(chemin, contenu)
    if ext in (".xlsx", ".xlsm"):
        return _lire_xlsx(chemin, contenu)
    if ext == ".pdf":
        return _lire_pdf(chemin, contenu)
    if ext in (".csv", ".txt"):
        return _lire_csv(chemin, contenu)
    raise ValueError(f"Format non pris en charge : {ext}")


def _lire_xls(chemin, contenu):
    import xlrd
    wb = xlrd.open_workbook(file_contents=contenu) if contenu else xlrd.open_workbook(chemin)
    sheets = []
    for sh in wb.sheets():
        grid = []
        for r in range(sh.nrows):
            ligne = []
            for c in range(sh.ncols):
                v = sh.cell_value(r, c)
                if isinstance(v, float) and v == int(v) and abs(v) < 1e15:
                    v = int(v)
                ligne.append("" if v is None else str(v).strip())
            grid.append(ligne)
        sheets.append({"name": sh.name, "grid": grid})
    return {"kind": "xls", "sheets": sheets}


def _lire_xlsx(chemin, contenu):
    import openpyxl
    src = io.BytesIO(contenu) if contenu else chemin
    wb = openpyxl.load_workbook(src, data_only=True, read_only=True)
    sheets = []
    for sh in wb.worksheets:
        grid = []
        for row in sh.iter_rows(values_only=True):
            grid.append(["" if v is None else str(v).strip() for v in row])
        sheets.append({"name": sh.title, "grid": grid})
    return {"kind": "xlsx", "sheets": sheets}


def _lire_csv(chemin, contenu):
    import csv
    txt = contenu.decode("utf-8", "replace") if contenu else open(chemin, encoding="utf-8", errors="replace").read()
    dialecte = csv.Sniffer().sniff(txt[:4000], delimiters=";,\t|") if txt.strip() else csv.excel
    grid = [list(r) for r in csv.reader(io.StringIO(txt), dialecte)]
    return {"kind": "csv", "sheets": [{"name": "csv", "grid": grid}]}


def _lire_pdf(chemin, contenu):
    """Détecte les colonnes par les gouttières blanches entre les mots.

    C'est la seule méthode fiable : un PDF tabulaire n'a pas de cellules, et le
    texte brut colle les colonnes entre elles (les séparateurs de milliers sont
    des espaces, donc « 4 150 4 776 » est illisible en ligne).
    """
    import pdfplumber
    src = io.BytesIO(contenu) if contenu else chemin
    sheets = []
    with pdfplumber.open(src) as pdf:
        mots_par_page, largeur = [], 0
        for p in pdf.pages:
            mots_par_page.append(p.extract_words(use_text_flow=False))
            largeur = max(largeur, p.width)

        def grouper(mots):
            lignes = {}
            for m in mots:
                lignes.setdefault(round(m["top"] / 3.0), []).append(m)   # tolérance de ligne
            return [sorted(lignes[k], key=lambda w: w["x0"]) for k in sorted(lignes)]

        # Les gouttières se mesurent sur les LIGNES DE DONNÉES seulement : les
        # titres et les en-têtes s'étalent en travers des colonnes et boucheraient
        # les blancs (« Length (cm) Width (cm)Height » est un bloc continu).
        occup = [0] * (int(largeur) + 2)
        n_donnees = 0
        for mots in mots_par_page:
            for ligne in grouper(mots):
                if sum(1 for m in ligne if _nombre(m["text"]) is not None) < 3:
                    continue
                n_donnees += 1
                for m in ligne:
                    for x in range(int(m["x0"]), min(int(m["x1"]) + 1, len(occup))):
                        occup[x] += 1
        if not n_donnees:                                # pas de table détectable
            occup = [1] * len(occup)

        seuil = max(1, int(n_donnees * 0.02))            # tolère quelques débordements
        bornes, dans_gouttiere, debut = [], False, 0
        for x, n in enumerate(occup):
            vide = n < seuil
            if vide and not dans_gouttiere:
                dans_gouttiere, debut = True, x
            elif not vide and dans_gouttiere:
                dans_gouttiere = False
                if x - debut >= 3:                       # gouttière significative
                    bornes.append((debut + x) / 2)
        bornes = [b for b in bornes if 0 < b < largeur]

        def colonne(xc):
            i = 0
            while i < len(bornes) and xc > bornes[i]:
                i += 1
            return i

        ncols = len(bornes) + 1
        tout = []
        for num, mots in enumerate(mots_par_page, 1):
            grid = []
            for ligne in grouper(mots):
                cellules = [[] for _ in range(ncols)]
                for m in ligne:
                    cellules[colonne((m["x0"] + m["x1"]) / 2)].append(m["text"])
                grid.append([" ".join(c).strip() for c in cellules])
            sheets.append({"name": f"page {num}", "grid": grid})
            tout.extend(grid)
    # Un tableau de packing list se poursuit d'une page à l'autre : la feuille
    # « document entier » est presque toujours celle qu'il faut lire.
    if len(sheets) > 1:
        sheets.insert(0, {"name": f"document entier ({len(sheets)} pages)", "grid": tout})
    return {"kind": "pdf", "sheets": sheets}


# ------------------------------------------------------- détection de structure

def deviner_entete(grid):
    """Trouve la ligne d'en-tête : celle qui contient le plus de libellés connus."""
    meilleur, score_max = 0, 0
    for r, ligne in enumerate(grid[:60]):
        blob = " | ".join(_norm(c) for c in ligne)
        score = sum(1 for mots in INDICES.values() for m in mots if m in blob)
        score += 2 * sum(1 for a in ANCRE_DIMS if a in blob)
        if score > score_max:
            meilleur, score_max = r, score
    return meilleur if score_max >= 3 else 0


def deviner_mapping(grid, entete):
    """Propose une correspondance colonne → champ.

    Deux passes : les libellés explicites, puis le cas « MEASUREMENTS IN CM »
    où L, l et h partagent un en-tête fusionné et sont retrouvés par la position
    des valeurs numériques dans les lignes de données.
    """
    if not grid or entete >= len(grid):
        return {}
    ncols = max(len(l) for l in grid)
    # on agrège l'en-tête et les 2 lignes suivantes (sous-titres NET / GROSS…)
    libelles = []
    for c in range(ncols):
        parts = []
        for r in range(entete, min(entete + 3, len(grid))):
            if c < len(grid[r]) and grid[r][c]:
                parts.append(grid[r][c])
        libelles.append(_norm(" ".join(parts)))

    mapping, pris = {}, set()
    for champ, mots in INDICES.items():
        for mot in mots:
            for c, lib in enumerate(libelles):
                if c in pris or not lib:
                    continue
                if mot in lib:
                    mapping[champ], _ = c, pris.add(c)
                    break
            if champ in mapping:
                break

    # cas des dimensions fusionnées
    if not {"length", "width", "height"} <= set(mapping):
        col_dim = next((c for c, lib in enumerate(libelles) if any(a in lib for a in ANCRE_DIMS)), None)
        fin = min([mapping[k] for k in ("gross", "net", "volume") if k in mapping] or [ncols])
        if col_dim is not None and fin > col_dim:
            compte = {}
            for ligne in grid[entete + 1: entete + 40]:
                for c in range(col_dim, min(fin, len(ligne))):
                    if _nombre(ligne[c]) is not None:
                        compte[c] = compte.get(c, 0) + 1
            cols = [c for c, n in sorted(compte.items()) if n >= 2][:3]
            if len(cols) == 3:
                for champ, c in zip(("length", "width", "height"), cols):
                    mapping[champ], _ = c, pris.add(c)

    # dimensions partiellement trouvées (fréquent en PDF, où « Width (cm)Height »
    # forme un seul mot) : on complète par les colonnes numériques suivantes
    manquants = [k for k in ("length", "width", "height") if k not in mapping]
    if manquants and len(manquants) < 3:
        numeriques = {}
        for ligne in grid[entete + 1: entete + 60]:
            for c in range(ncols):
                if c < len(ligne) and _nombre(ligne[c]) is not None:
                    numeriques[c] = numeriques.get(c, 0) + 1
        seuil = max(numeriques.values()) * 0.4 if numeriques else 0
        depart = min(mapping[k] for k in ("length", "width", "height") if k in mapping)
        libres = [c for c, n in sorted(numeriques.items())
                  if c > depart and c not in pris and n >= seuil]
        for champ in ("length", "width", "height"):
            if champ in mapping or not libres:
                continue
            mapping[champ] = libres.pop(0)
            pris.add(mapping[champ])

    # à défaut de désignation identifiée, la colonne texte la plus large
    if "desc" not in mapping:
        longueurs = {}
        for ligne in grid[entete + 1: entete + 40]:
            for c, v in enumerate(ligne):
                if c not in pris and v and _nombre(v) is None:
                    longueurs[c] = longueurs.get(c, 0) + len(v)
        if longueurs:
            mapping["desc"] = max(longueurs, key=longueurs.get)
    return mapping


def deviner_unite(grid, entete, mapping):
    """cm, mm ou m ? On lit l'en-tête, puis on recoupe avec les ordres de grandeur."""
    blob = " ".join(_norm(c) for r in grid[max(0, entete - 1): entete + 3] for c in r)
    if re.search(r"\bin mm\b|\(mm\)|en mm", blob):
        return "mm"
    if re.search(r"\bin cm\b|\(cm\)|en cm", blob):
        return "cm"
    vals = []
    for ligne in grid[entete + 1: entete + 60]:
        for champ in ("length", "width", "height"):
            c = mapping.get(champ)
            if c is not None and c < len(ligne):
                v = _nombre(ligne[c])
                if v:
                    vals.append(v)
    if not vals:
        return "cm"
    m = max(vals)
    if m > 3000:
        return "mm"
    if m < 25:
        return "m"
    return "cm"


# ----------------------------------------------------------------- construction

FACTEUR = {"mm": 0.1, "cm": 1.0, "m": 100.0, "in": 2.54}


def construire(grid, entete, mapping, unite="cm", regrouper=True, defaut_gerbable="no"):
    """Grille + mapping → liste de colis normalisés, avec diagnostics."""
    f = FACTEUR.get(unite, 1.0)
    get = lambda ligne, champ: (ligne[mapping[champ]] if champ in mapping and mapping[champ] < len(ligne) else "")

    colis, ignorees, rattachees = [], 0, 0
    for r in range(entete + 1, len(grid)):
        ligne = grid[r]
        if not any(str(c).strip() for c in ligne):
            continue
        texte = " ".join(str(c) for c in ligne).upper()
        if "A REPORTER" in texte or texte.strip().startswith("TOTAL"):
            continue

        L = _nombre(get(ligne, "length"))
        W = _nombre(get(ligne, "width"))
        H = _nombre(get(ligne, "height"))
        ref = str(get(ligne, "ref")).strip()
        desc = str(get(ligne, "desc")).strip()

        if not (L and W and H):
            # ligne de contenu supplémentaire rattachée au colis précédent
            if regrouper and colis and not ref and desc:
                colis[-1]["desc"] = (colis[-1]["desc"] + " ; " + desc)[:400]
                colis[-1]["lignes_source"] += 1
                rattachees += 1
            else:
                ignorees += 1
            continue

        brut = _nombre(get(ligne, "gross"))
        net = _nombre(get(ligne, "net"))
        colis.append({
            "id": len(colis) + 1,
            "ref": ref or f"L{r + 1}",
            "desc": desc[:400],
            "qty": int(_nombre(get(ligne, "qty")) or 1),
            "length": round(L * f, 1),
            "width": round(W * f, 1),
            "height": round(H * f, 1),
            "gross": round(brut, 1) if brut else 0.0,
            "net": round(net, 1) if net else 0.0,
            "volume_declare": _nombre(get(ligne, "volume")),
            "group": str(get(ligne, "group")).strip(),
            "supplier": str(get(ligne, "supplier")).strip(),
            # champs métier saisis par l'équipe
            "stackable": defaut_gerbable,     # no | yes | same
            "max_load": None,                 # kg admissibles sur le dessus
            "rotatable": True,                # rotation 90° au sol autorisée
            "bottom_only": False,             # doit rester au sol
            # cotes toutes rondes = probable estimation en attendant la mesure
            "status": "estimated" if all(round(x * f) % 50 == 0 for x in (L, W, H)) else "confirmed",
            "note": "",
            "ligne_source": r + 1,
            "lignes_source": 1,
        })

    diag = {"lignes_ignorees": ignorees, "lignes_rattachees": rattachees}
    return colis, diag


# ------------------------------------------------------------------- contrôles

def controler(colis, grid=None):
    """Contrôles de cohérence. Retourne les alertes par colis + un bilan global."""
    alertes = {}

    def ajoute(c, niveau, texte):
        alertes.setdefault(c["id"], []).append({"niveau": niveau, "texte": texte})

    vus = {}
    for c in colis:
        vol = c["length"] * c["width"] * c["height"] / 1e6
        c["volume_calcule"] = round(vol, 3)

        if not c["gross"]:
            ajoute(c, "warn", "poids brut absent — le contrôle de charge sera faux")
        if c["net"] and c["gross"] and c["net"] > c["gross"]:
            ajoute(c, "err", f"poids net ({c['net']:.0f}) supérieur au brut ({c['gross']:.0f})")

        vd = c.get("volume_declare")
        if vd and vol and abs(vol - vd) / vd > 0.10:
            ajoute(c, "err", f"volume déclaré {vd:g} m³ ≠ L×l×h calculé {vol:.3f} m³")

        if c["gross"] and vol:
            d = c["gross"] / vol
            if d < 15:
                ajoute(c, "warn", f"densité très faible ({d:.0f} kg/m³) — cote ou poids douteux")
            elif d > 3000:
                ajoute(c, "warn", f"densité très forte ({d:.0f} kg/m³) — cote ou poids douteux")

        if all(x % 50 == 0 for x in (c["length"], c["width"], c["height"])):
            ajoute(c, "warn", "les trois cotes sont des multiples de 50 cm — probable estimation")

        cle = (c["ref"] or "").strip().lower()
        if cle:
            if cle in vus:
                ajoute(c, "warn", f"référence en doublon avec la ligne {vus[cle]}")
            else:
                vus[cle] = c["ligne_source"]

    bilan = {
        "colis": len(colis),
        "volume": round(sum(c["volume_calcule"] for c in colis), 2),
        "brut": round(sum(c["gross"] for c in colis)),
        "net": round(sum(c["net"] for c in colis)),
        "erreurs": sum(1 for a in alertes.values() for x in a if x["niveau"] == "err"),
        "avertissements": sum(1 for a in alertes.values() for x in a if x["niveau"] == "warn"),
    }

    # réconciliation avec la ligne TOTAL du document, si on la retrouve
    if grid:
        bilan["totaux_document"] = _totaux_document(grid, bilan)
    return alertes, bilan


MARQUEURS_TOTAL = re.compile(r"\bTOTAL\b|A REPORTER|GRAND TOTAL|TOTAUX", re.I)


def _totaux_document(grid, bilan):
    """Cherche les totaux annoncés par le document et les compare aux nôtres.

    Ce contrôle attrape les erreurs de LECTURE (mapping ou en-tête erronés, lignes
    perdues). Il n'attrape pas les erreurs de SAISIE : si une valeur est fausse
    dans le fichier, le total du document l'est aussi. D'où les contrôles ligne à
    ligne de `controler()`, qui sont complémentaires.

    Le total peut être sur la ligne du marqueur ou sur l'une des deux suivantes
    (cas fréquent d'un bandeau « TOTAL GROSS WEIGHT » suivi de ses valeurs).
    """
    meilleur = None
    for i, ligne in enumerate(grid):
        if not MARQUEURS_TOTAL.search(" ".join(str(c) for c in ligne)):
            continue
        nombres = []
        for j in range(i, min(i + 3, len(grid))):
            nombres += [n for n in (_nombre(c) for c in grid[j]) if n]
        if not nombres:
            continue
        res = {}
        for cible, cle, tol in ((bilan["brut"], "brut", 0.20),
                                (bilan["volume"], "volume", 0.20),
                                # le nombre de colis n'a de valeur que s'il tombe juste :
                                # sinon on capte n'importe quel entier voisin de la ligne
                                (bilan["colis"], "colis", 0.02)):
            if not cible:
                continue
            proche = min(nombres, key=lambda n: abs(n - cible) / max(cible, 1))
            ecart = abs(proche - cible) / max(cible, 1)
            if ecart < tol:
                res[cle] = {"document": proche, "calcule": cible,
                            "ecart_pct": round(ecart * 100, 2)}
        # on retient la ligne qui recoupe le plus de grandeurs, la plus fidèle d'abord
        if res and (meilleur is None or
                    (len(res), -sum(v["ecart_pct"] for v in res.values())) >
                    (len(meilleur), -sum(v["ecart_pct"] for v in meilleur.values()))):
            meilleur = res
    return meilleur
