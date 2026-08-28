#!/usr/bin/env bash
# ---------------------------------------------------------------
# Lanceur macOS / Linux : crée l'environnement virtuel au premier
# appel, puis lance l'analyse multi-fissures.
#
#   ./run.sh                          -> fenêtre de choix de l'image
#   ./run.sh mon_image.png            -> analyse directement cette image
#   ./run.sh mon_image.png --show-cost
# ---------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
    echo "[1/2] Création de l'environnement virtuel .venv ..."
    if command -v python3 >/dev/null 2>&1; then
        PYCMD=python3
    elif command -v python >/dev/null 2>&1; then
        PYCMD=python
    else
        echo
        echo "ERREUR : Python est introuvable sur cette machine."
        echo "Installe Python 3.10 ou plus récent, puis relance ce script."
        exit 1
    fi

    "$PYCMD" -m venv .venv

    echo "[2/2] Installation des dépendances (compter quelques minutes) ..."
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -r requirements.txt
    echo "Installation terminée."
    echo
fi

exec .venv/bin/python crack_length_analysis_multi.py "$@"
