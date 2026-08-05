"""Moteur de placement 3D.

Heuristique des points extrêmes + insertion first-fit par volume décroissant.
Rotation autour de l'axe vertical uniquement (un colis industriel ne se couche
pas), et respect des contraintes métier saisies par l'équipe :

  stackable    no | yes | same   — peut-on poser quelque chose SUR ce colis
  max_load     kg admissibles sur le dessus (cumulés, propagés vers le bas)
  rotatable    rotation 90° au sol autorisée
  bottom_only  doit rester au sol
"""

from gabarit import UNITS, classify, solution_hors_gabarit

APPUI_MINI = 0.70          # part de la base qui doit reposer sur du solide
TOL_MEME_EMPREINTE = 3.0   # cm de tolérance pour « gerbable sur identique »


def _chevauche(a, b):
    return not (a[0] + a[3] <= b[0] or b[0] + b[3] <= a[0] or
                a[1] + a[4] <= b[1] or b[1] + b[4] <= a[1] or
                a[2] + a[5] <= b[2] or b[2] + b[5] <= a[2])


class Bin:
    def __init__(self, unit_key, clearance):
        U = UNITS[unit_key]
        self.unit = unit_key
        self.CL, self.CW, self.CH = U["L"] - clearance, U["W"] - clearance, U["H"] - clearance
        self.pay = U["pay"]
        self.cap = U["L"] * U["W"] * U["H"] / 1e6
        self.boxes = []          # dicts : x,y,z,l,w,h,colis,charge,supports
        self.points = {(0.0, 0.0, 0.0)}
        self.kg = 0.0
        self.vol = 0.0

    @property
    def fill(self):
        return self.vol / self.cap * 100 if self.cap else 0

    # ---------------------------------------------------------------- appui
    def _supports(self, x, y, z, l, w):
        """Colis dont le dessus est au niveau z et qui portent la base."""
        out, aire = [], 0.0
        for b in self.boxes:
            if abs(b["z"] + b["h"] - z) > 1.0:
                continue
            ox = max(0.0, min(x + l, b["x"] + b["l"]) - max(x, b["x"]))
            oy = max(0.0, min(y + w, b["y"] + b["w"]) - max(y, b["y"]))
            if ox > 0 and oy > 0:
                out.append(b)
                aire += ox * oy
        return out, (aire / (l * w) if l * w else 0)

    def _charge_ok(self, supports, kg):
        """Propage le poids vers le bas et vérifie chaque charge admissible."""
        vus, pile, cumul = set(), list(supports), {}
        while pile:
            b = pile.pop()
            if id(b) in vus:
                continue
            vus.add(id(b))
            cumul[id(b)] = b["charge"] + kg
            mx = b["colis"].get("max_load")
            if mx and cumul[id(b)] > float(mx):
                return None
            pile.extend(b["supports"])
        return vus

    def peut_poser(self, colis, x, y, z, l, w, h):
        if x + l > self.CL + 1e-6 or y + w > self.CW + 1e-6 or z + h > self.CH + 1e-6:
            return None
        cand = (x, y, z, l, w, h)
        if any(_chevauche(cand, (b["x"], b["y"], b["z"], b["l"], b["w"], b["h"])) for b in self.boxes):
            return None
        if z <= 1e-6:
            return []
        if colis.get("bottom_only"):
            return None
        supports, couverture = self._supports(x, y, z, l, w)
        if not supports or couverture < APPUI_MINI:
            return None
        for s in supports:
            st = s["colis"].get("stackable", "no")
            if st == "no":
                return None
            if st == "same" and (abs(s["l"] - l) > TOL_MEME_EMPREINTE or abs(s["w"] - w) > TOL_MEME_EMPREINTE):
                return None
        return supports

    def poser(self, colis, x, y, z, l, w, h, supports):
        kg = float(colis.get("gross") or 0)
        touches = self._charge_ok(supports, kg)
        if touches is None:
            return False
        for b in self.boxes:
            if id(b) in touches:
                b["charge"] += kg
        self.boxes.append(dict(x=x, y=y, z=z, l=l, w=w, h=h,
                               colis=colis, charge=0.0, supports=list(supports)))
        self.kg += kg
        self.vol += l * w * h / 1e6
        self.points.discard((x, y, z))
        for p in ((x + l, y, z), (x, y + w, z), (x, y, z + h)):
            if p[0] < self.CL and p[1] < self.CW and p[2] < self.CH:
                self.points.add(p)
        if len(self.points) > 600:
            self.points = set(sorted(self.points, key=lambda p: (p[2], p[1], p[0]))[:600])
        return True

    def essayer(self, colis, plafond, clearance):
        kg = float(colis.get("gross") or 0)
        if self.kg + kg > self.pay:
            return False
        l0 = colis["length"] + clearance
        w0 = colis["width"] + clearance
        h = colis["height"]
        # Le plafond est ferme : un plan trop dense n'est pas arrimable. On ne
        # l'ignore que pour le tout premier colis, sinon un colis volumineux ne
        # trouverait jamais de place nulle part.
        if self.boxes and (self.vol + l0 * w0 * h / 1e6) / self.cap * 100 > plafond:
            return False
        orientations = [(l0, w0)] + ([(w0, l0)] if colis.get("rotatable", True) else [])
        for (x, y, z) in sorted(self.points, key=lambda p: (p[2], p[1], p[0])):
            for (l, w) in orientations:
                sup = self.peut_poser(colis, x, y, z, l, w, h)
                if sup is not None and self.poser(colis, x, y, z, l, w, h, sup):
                    return True
        return False


def _packer_liste(colis, unit_key, plafond, clearance):
    bins = []
    for c in sorted(colis, key=lambda c: -(c["length"] * c["width"] * c["height"])):
        if any(b.essayer(c, plafond, clearance) for b in bins):
            continue
        b = Bin(unit_key, clearance)
        if not b.essayer(c, 100.0, clearance):
            return None, c          # ne rentre même pas seul
        bins.append(b)
    return bins, None


def _plus_petite_unite(bin_, unites, clearance):
    """Peut-on redescendre ce conteneur sur une unité plus petite ?"""
    contenu = [b["colis"] for b in bin_.boxes]
    ordre = sorted(unites, key=lambda u: UNITS[u]["L"] * UNITS[u]["W"] * UNITS[u]["H"])
    for u in ordre:
        if UNITS[u]["L"] * UNITS[u]["W"] * UNITS[u]["H"] >= UNITS[bin_.unit]["L"] * UNITS[bin_.unit]["W"] * UNITS[bin_.unit]["H"]:
            break
        essai, echec = _packer_liste(contenu, u, 100.0, clearance)
        if essai and len(essai) == 1:
            return essai[0]
    return bin_


def planifier(colis, unites=None, plafond=85.0, clearance=0.0,
              limite_cm=10.0, grouper_par=None, optimiser_unite=True):
    """Calcule le plan complet.

    Retourne { unites: [...], hors_gabarit: [...], resume: {...} }
    """
    unites = unites or ["40HC"]
    principale = max(unites, key=lambda u: UNITS[u]["L"] * UNITS[u]["W"] * UNITS[u]["H"])

    # 1. tri gabarit
    standard, hg = [], []
    for c in colis:
        verdicts = [classify(c, u, clearance, limite_cm) for u in unites]
        if all(v[0] == "hors_gabarit" for v in verdicts):
            sol, motif = solution_hors_gabarit(c)
            best = min(verdicts, key=lambda v: -v[1])
            hg.append({"colis": c, "solution": sol, "motif": motif, "motifs": best[2]})
        else:
            v = next(v for v, u in zip(verdicts, unites) if v[0] != "hors_gabarit")
            c["_verdict"] = v[0]
            c["_marge"] = round(v[1], 1)
            standard.append(c)

    # 2. groupes
    if grouper_par:
        groupes = {}
        for c in standard:
            groupes.setdefault(str(c.get(grouper_par) or "—"), []).append(c)
    else:
        groupes = {"tout": standard}

    # 3. placement
    resultat, refuses = [], []
    for nom, lot in sorted(groupes.items()):
        bins, echec = _packer_liste(lot, principale, plafond, clearance)
        if bins is None:
            refuses.append(echec)
            lot = [c for c in lot if c is not echec]
            bins, _ = _packer_liste(lot, principale, plafond, clearance)
        for b in (bins or []):
            if optimiser_unite and len(unites) > 1:
                b = _plus_petite_unite(b, unites, clearance)
            U = UNITS[b.unit]
            resultat.append({
                "groupe": nom,
                "unite": b.unit,
                "unite_label": U["label"],
                "dims": [U["L"], U["W"], U["H"]],
                "remplissage": round(b.fill, 1),
                "poids": round(b.kg),
                "charge_utile": U["pay"],
                "volume": round(b.vol, 2),
                "colis": [{
                    "id": bb["colis"]["id"], "ref": bb["colis"]["ref"],
                    "desc": bb["colis"]["desc"][:70],
                    "x": round(bb["x"], 1), "y": round(bb["y"], 1), "z": round(bb["z"], 1),
                    "l": round(bb["l"], 1), "w": round(bb["w"], 1), "h": round(bb["h"], 1),
                    "kg": bb["colis"]["gross"],
                    "charge_dessus": round(bb["charge"]),
                    "niveau": 0 if bb["z"] < 1 else 1,
                } for bb in sorted(b.boxes, key=lambda bb: (bb["z"], bb["x"], bb["y"]))],
            })

    vol_std = sum(c["length"] * c["width"] * c["height"] / 1e6 for c in standard)
    cout = sum(UNITS[u["unite"]]["cost"] for u in resultat)
    return {
        "unites": resultat,
        "hors_gabarit": [{
            "id": h["colis"]["id"], "ref": h["colis"]["ref"], "desc": h["colis"]["desc"][:70],
            "dims": [h["colis"]["length"], h["colis"]["width"], h["colis"]["height"]],
            "kg": h["colis"]["gross"],
            "volume": round(h["colis"]["length"] * h["colis"]["width"] * h["colis"]["height"] / 1e6, 2),
            "solution": h["solution"], "motif": h["motif"], "motifs": h["motifs"],
        } for h in hg],
        "resume": {
            "colis_total": len(colis),
            "colis_standard": len(standard),
            "colis_hors_gabarit": len(hg),
            "colis_limite": sum(1 for c in standard if c.get("_verdict") == "limite"),
            "colis_refuses": len(refuses),
            "nb_unites": len(resultat),
            "volume_standard": round(vol_std, 2),
            "volume_hors_gabarit": round(sum(h["colis"]["length"] * h["colis"]["width"] * h["colis"]["height"] / 1e6 for h in hg), 2),
            "remplissage_moyen": round(sum(u["remplissage"] for u in resultat) / len(resultat), 1) if resultat else 0,
            "indice_cout": round(cout, 2),
            "detail_unites": _compter(resultat),
        },
    }


def _compter(resultat):
    out = {}
    for u in resultat:
        out[u["unite_label"]] = out.get(u["unite_label"], 0) + 1
    return out
