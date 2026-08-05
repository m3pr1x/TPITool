"""Serveur de l'outil de plan de chargement / empotage.

En local  :  ./demarrer.command   (ou : python -m uvicorn app:app --port 8000)
En ligne  :  uvicorn app:app --host 0.0.0.0 --port $PORT

Variables d'environnement facultatives :
  PORT              port d'écoute (défaut 8000) — renseigné par les hébergeurs
  TPITOOL_MDP       si défini, l'accès est protégé par mot de passe (identifiant libre)
  TPITOOL_MAX_MO    taille maximale d'un fichier importé, en Mo (défaut 30)
"""

import csv
import io
import os
import secrets
import time
import uuid

from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import ingest
import packer
from gabarit import UNITS, classify

ICI = os.path.dirname(os.path.abspath(__file__))
MDP = os.environ.get("TPITOOL_MDP", "").strip()
MAX_OCTETS = int(float(os.environ.get("TPITOOL_MAX_MO", "30")) * 1024 * 1024)

app = FastAPI(title="Plan de chargement & d'empotage", docs_url=None, redoc_url=None)

# Sessions en mémoire : le fichier importé n'est jamais écrit sur disque.
SESSIONS = {}
SESSION_TTL = 60 * 60          # une heure d'inactivité
SESSIONS_MAX = 20              # garde-fou mémoire si plusieurs personnes utilisent le lien


def _purger_sessions():
    """Évite que la mémoire enfle : on jette les vieilles sessions, puis les plus anciennes."""
    limite = time.time() - SESSION_TTL
    for cle in [k for k, v in SESSIONS.items() if v["t"] < limite]:
        SESSIONS.pop(cle, None)
    while len(SESSIONS) > SESSIONS_MAX:
        SESSIONS.pop(min(SESSIONS, key=lambda k: SESSIONS[k]["t"]), None)


@app.middleware("http")
async def protection(request: Request, call_next):
    """Mot de passe facultatif — indispensable dès que l'app est exposée sur Internet,
    puisque n'importe qui pourrait sinon y déposer des fichiers."""
    if MDP:
        entete = request.headers.get("authorization", "")
        ok = False
        if entete.startswith("Basic "):
            try:
                import base64
                _, _, fourni = base64.b64decode(entete[6:]).decode("utf-8").partition(":")
                ok = secrets.compare_digest(fourni, MDP)
            except Exception:
                ok = False
        if not ok:
            return Response(status_code=401, content="Accès protégé.",
                            headers={"WWW-Authenticate": 'Basic realm="Plan de chargement"'})
    return await call_next(request)


# --------------------------------------------------------------------- modèles

class Mapping(BaseModel):
    session: str
    sheet: int = 0
    entete: int = 0
    mapping: dict
    unite: str = "cm"
    regrouper: bool = True
    defaut_gerbable: str = "no"


class Plan(BaseModel):
    colis: list
    unites: list = ["40HC"]
    plafond: float = 85.0
    clearance: float = 0.0
    limite_cm: float = 10.0
    grouper_par: str | None = None
    optimiser_unite: bool = True
    # plan déjà calculé et éventuellement réagencé à la main dans la vue 3D :
    # s'il est fourni, l'export le reprend tel quel au lieu de recalculer.
    plan: dict | None = None


# ---------------------------------------------------------------------- routes

@app.get("/", response_class=HTMLResponse)
def accueil():
    with open(os.path.join(ICI, "static", "index.html"), encoding="utf-8") as f:
        return f.read()


@app.get("/api/unites")
def unites():
    return {"unites": [dict(cle=k, **v) for k, v in UNITS.items()],
            "champs": ingest.CHAMPS}


@app.post("/api/import")
async def importer(fichier: UploadFile = File(...)):
    contenu = await fichier.read()
    if len(contenu) > MAX_OCTETS:
        raise HTTPException(413, f"Fichier trop volumineux ({MAX_OCTETS // (1024*1024)} Mo maximum).")
    try:
        doc = ingest.lire_fichier(fichier.filename or "", contenu)
    except Exception as e:
        raise HTTPException(400, f"Lecture impossible : {e}")

    if not doc["sheets"]:
        raise HTTPException(400, "Aucune feuille ni page exploitable dans ce fichier.")

    # On retient la feuille la plus fournie comme proposition par défaut.
    defaut = max(range(len(doc["sheets"])),
                 key=lambda i: sum(1 for l in doc["sheets"][i]["grid"] if any(l)))

    _purger_sessions()
    sid = uuid.uuid4().hex[:12]
    SESSIONS[sid] = {"doc": doc, "nom": fichier.filename, "t": time.time()}

    feuilles = []
    for sh in doc["sheets"]:
        grid = sh["grid"]
        entete = ingest.deviner_entete(grid)
        mapping = ingest.deviner_mapping(grid, entete)
        feuilles.append({
            "nom": sh["name"],
            "lignes": len(grid),
            "colonnes": max((len(l) for l in grid), default=0),
            "entete_propose": entete,
            "mapping_propose": mapping,
            "unite_proposee": ingest.deviner_unite(grid, entete, mapping),
            "apercu": [l[:40] for l in grid[:60]],
        })
    return {"session": sid, "nom": fichier.filename, "type": doc["kind"],
            "feuille_defaut": defaut, "feuilles": feuilles}


@app.post("/api/parser")
def parser(req: Mapping):
    s = SESSIONS.get(req.session)
    if not s:
        raise HTTPException(404, "Session expirée — réimporte le fichier.")
    s["t"] = time.time()
    if not 0 <= req.sheet < len(s["doc"]["sheets"]):
        raise HTTPException(400, "Feuille inexistante.")
    grid = s["doc"]["sheets"][req.sheet]["grid"]
    mapping = {k: int(v) for k, v in req.mapping.items() if v not in (None, "", -1)}
    if not {"length", "width", "height"} <= set(mapping):
        raise HTTPException(400, "Il faut au minimum désigner les colonnes longueur, largeur et hauteur.")

    colis, diag = ingest.construire(grid, req.entete, mapping, req.unite,
                                    req.regrouper, req.defaut_gerbable)
    if not colis:
        raise HTTPException(400, "Aucun colis lisible avec ce mapping. Vérifie la ligne d'en-tête.")
    alertes, bilan = ingest.controler(colis, grid)
    bilan.update(diag)
    return {"colis": colis, "alertes": alertes, "bilan": bilan}


@app.post("/api/controler")
def controler(req: Plan):
    """Rejoue les contrôles de cohérence après édition manuelle."""
    colis = [dict(c) for c in req.colis]
    alertes, bilan = ingest.controler(colis, None)
    return {"alertes": alertes, "bilan": bilan}


@app.post("/api/verifier")
def verifier(req: Plan):
    """Reclasse les colis après édition, sans lancer le placement."""
    out = {}
    for c in req.colis:
        v = [classify(c, u, req.clearance, req.limite_cm) for u in req.unites]
        meilleur = max(v, key=lambda x: x[1])
        out[c["id"]] = {"verdict": meilleur[0], "marge": round(meilleur[1], 1),
                        "motifs": meilleur[2]}
    return {"gabarit": out}


@app.post("/api/plan")
def plan(req: Plan):
    if not req.colis:
        raise HTTPException(400, "Aucun colis à placer.")
    if not req.unites:
        raise HTTPException(400, "Choisis au moins une unité de transport.")
    res = packer.planifier([dict(c) for c in req.colis], req.unites, req.plafond,
                           req.clearance, req.limite_cm, req.grouper_par,
                           req.optimiser_unite)
    return res


@app.post("/api/export/colis")
def export_colis(req: Plan):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["ref", "designation", "longueur_cm", "largeur_cm", "hauteur_cm",
                "poids_brut_kg", "volume_m3", "gerbable", "charge_max_kg",
                "rotation", "au_sol", "statut", "expedition", "fournisseur", "note"])
    for c in req.colis:
        w.writerow([c.get("ref"), c.get("desc"), c.get("length"), c.get("width"),
                    c.get("height"), c.get("gross"),
                    round(c["length"] * c["width"] * c["height"] / 1e6, 3),
                    {"no": "non", "yes": "oui", "same": "sur identique"}.get(c.get("stackable"), ""),
                    c.get("max_load") or "", "oui" if c.get("rotatable") else "non",
                    "oui" if c.get("bottom_only") else "non", c.get("status"),
                    c.get("group"), c.get("supplier"), c.get("note")])
    return _csv(buf, "colis-verifies.csv")


@app.post("/api/export/plan")
def export_plan(req: Plan):
    res = req.plan or packer.planifier([dict(c) for c in req.colis], req.unites, req.plafond,
                                       req.clearance, req.limite_cm, req.grouper_par,
                                       req.optimiser_unite)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["unite_n", "groupe", "type_unite", "remplissage_pct", "poids_kg",
                "colis_ref", "designation", "x_cm", "y_cm", "z_cm",
                "longueur_cm", "largeur_cm", "hauteur_cm", "poids_colis_kg", "charge_dessus_kg"])
    for i, u in enumerate(res["unites"], 1):
        for c in u["colis"]:
            w.writerow([i, u["groupe"], u["unite_label"], u["remplissage"], u["poids"],
                        c["ref"], c["desc"], c["x"], c["y"], c["z"],
                        c["l"], c["w"], c["h"], c["kg"], c["charge_dessus"]])
    for h in res["hors_gabarit"]:
        w.writerow(["HG", "", h["solution"], "", "", h["ref"], h["desc"], "", "", "",
                    h["dims"][0], h["dims"][1], h["dims"][2], h["kg"], ""])
    return _csv(buf, "plan-de-chargement.csv")


def _csv(buf, nom):
    data = "﻿" + buf.getvalue()          # BOM : Excel ouvre l'UTF-8 correctement
    return StreamingResponse(io.BytesIO(data.encode("utf-8")), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{nom}"'})


app.mount("/static", StaticFiles(directory=os.path.join(ICI, "static")), name="static")
app.mount("/exemples", StaticFiles(directory=os.path.join(ICI, "exemples")), name="exemples")


if __name__ == "__main__":
    import uvicorn
    # 0.0.0.0 dès qu'un PORT est imposé par l'hébergeur, 127.0.0.1 en local.
    port = int(os.environ.get("PORT", "8000"))
    hote = "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"
    uvicorn.run(app, host=hote, port=port)
