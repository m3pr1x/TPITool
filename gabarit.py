"""Référentiel des unités de transport et classification des colis.

Toutes les dimensions sont INTERNES, en centimètres.
Sources : CMA CGM (conteneurs maritimes), spécification tautliner standard.
"""

UNITS = {
    "20GP": dict(label="20' Dry",           L=590.0,  W=235.2, H=239.3, pay=28250, kind="conteneur", cost=1.00),
    "40GP": dict(label="40' Dry",           L=1203.4, W=235.2, H=239.5, pay=26760, kind="conteneur", cost=1.55),
    "40HC": dict(label="40' High Cube",     L=1203.4, W=235.2, H=270.0, pay=26580, kind="conteneur", cost=1.60),
    "45HC": dict(label="45' High Cube",     L=1355.6, W=235.2, H=270.0, pay=25780, kind="conteneur", cost=1.75),
    "20OT": dict(label="20' Open Top",      L=589.8,  W=235.0, H=234.8, pay=28100, kind="special",   cost=1.60),
    "40OT": dict(label="40' Open Top",      L=1204.3, W=235.0, H=234.8, pay=26580, kind="special",   cost=2.40),
    "20FR": dict(label="20' Flat Rack",     L=592.0,  W=222.4, H=221.3, pay=31250, kind="special",   cost=1.80),
    "40FR": dict(label="40' Flat Rack",     L=1205.4, W=222.7, H=195.9, pay=40100, kind="special",   cost=2.70),
    "TAUT": dict(label="Tautliner 13,6 m",  L=1362.0, W=248.0, H=270.0, pay=25000, kind="camion",    cost=1.00),
    "MEGA": dict(label="Méga 13,6 m",       L=1362.0, W=248.0, H=300.0, pay=24000, kind="camion",    cost=1.10),
    "PORT": dict(label="Porteur 7,2 m",     L=720.0,  W=245.0, H=250.0, pay=12000, kind="camion",    cost=0.60),
}

# Ordre de préférence quand l'outil doit choisir tout seul (du plus gros au plus petit).
PREFERENCE = ["45HC", "40HC", "40GP", "20GP"]

# Les unités "spéciales" acceptent le dépassement en hauteur (open top) ou en
# hauteur + largeur (flat rack), moyennant une déclaration hors gabarit.
OVERHEIGHT_OK = {"20OT", "40OT", "20FR", "40FR"}
OVERWIDTH_OK = {"20FR", "40FR"}


def footprint_fits(l, w, U, clearance=0.0):
    """Le colis tient-il au sol de l'unité, dans l'une des deux orientations ?"""
    cl, cw = U["L"] - clearance, U["W"] - clearance
    return (l <= cl and w <= cw) or (w <= cl and l <= cw)


def classify(colis, unit_key, clearance=0.0, limite_cm=10.0):
    """Retourne (verdict, marge_min_cm, motifs).

    verdict : "ok" | "limite" | "hors_gabarit"
    marge   : la plus petite marge restante, en cm (négative si dépassement)
    """
    U = UNITS[unit_key]
    l, w, h = float(colis["length"]), float(colis["width"]), float(colis["height"])
    kg = float(colis.get("gross") or 0)
    a, b = max(l, w), min(l, w)

    marges = {
        "longueur": U["L"] - clearance - a,
        "largeur": U["W"] - clearance - b,
        "hauteur": U["H"] - clearance - h,
    }
    motifs = [f"{k} dépassée de {abs(v):.0f} cm" for k, v in marges.items() if v < 0]
    if kg > U["pay"]:
        motifs.append(f"poids {kg:.0f} kg > charge utile {U['pay']} kg")

    marge_min = min(marges.values())
    if motifs:
        return "hors_gabarit", marge_min, motifs
    if marge_min <= limite_cm:
        cote = min(marges, key=marges.get)
        return "limite", marge_min, [f"{cote} : il ne reste que {marge_min:.0f} cm"]
    return "ok", marge_min, []


def solution_hors_gabarit(colis):
    """Que faire d'un colis qui ne rentre dans aucun conteneur fermé ?"""
    l, w, h = float(colis["length"]), float(colis["width"]), float(colis["height"])
    kg = float(colis.get("gross") or 0)
    a, b = max(l, w), min(l, w)
    over_w = b > 235.2
    over_h = h > 270.0
    over_l = a > 1355.6

    if over_l or kg > 40100:
        return "Conventionnel / breakbulk", "hors gabarit sur toutes les unités conteneurisées"
    if over_w:
        unit = "40FR" if a > 592 else "20FR"
        return f"{UNITS[unit]['label']} — déclaration OOG", "dépassement en largeur"
    if over_h:
        unit = "40OT" if a > 590 else "20OT"
        return f"{UNITS[unit]['label']} — déclaration OOG", "dépassement en hauteur seule"
    return "Flat rack — à arbitrer", "dépassement de charge ou cas particulier"
