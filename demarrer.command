#!/bin/bash
# Double-clique ce fichier pour lancer l'outil.
cd "$(dirname "$0")" || exit 1

if [ ! -d .venv ]; then
  echo "Première installation (une seule fois, ~1 minute)…"
  python3 -m venv .venv || { echo "Python 3 est introuvable."; read -r; exit 1; }
  ./.venv/bin/pip install --quiet --upgrade pip
  ./.venv/bin/pip install --quiet -r requirements.txt || { echo "Installation échouée."; read -r; exit 1; }
fi

echo ""
echo "  Outil de plan de chargement / empotage"
echo "  → ouvre http://127.0.0.1:8000 dans ton navigateur"
echo "  → ferme cette fenêtre (ou Ctrl-C) pour arrêter"
echo ""

( sleep 2 && open "http://127.0.0.1:8000" ) &
exec ./.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000
