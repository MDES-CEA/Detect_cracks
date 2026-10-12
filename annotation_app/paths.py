"""Emplacements du projet, quel que soit le dossier ou il a ete copie.

Tout se deduit de l'emplacement de ce fichier ; aucun chemin absolu. Deux
dossiers a ne pas confondre :

- `modeles/` : les reseaux de reperage. Ils font partie du code et voyagent
  avec lui d'un poste a l'autre ;
- `data/`    : l'etat propre a CE poste — base d'annotations, cache d'analyse,
  sauvegardes, derniere image ouverte.
"""

from __future__ import annotations

import os
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
MODELS_DIR = APP_DIR / "modeles"
DATA_DIR = APP_DIR / "data"
DEFAULT_DATABASE = DATA_DIR / "annotations.sqlite3"
LAST_IMAGE_FILE = DATA_DIR / "derniere_image.txt"
# La mosaique de reference est designee HORS du code, sur chaque poste : le
# depot ne contient ainsi aucun nom d'echantillon ni chemin personnel.
REFERENCE_IMAGE_FILE = DATA_DIR / "image_reference.txt"


def _recorded_image(record: Path) -> Path | None:
    try:
        text = record.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    path = Path(text) if text else None
    return path if path is not None and path.is_file() else None


def last_image(record: Path = LAST_IMAGE_FILE) -> Path | None:
    """Derniere mosaique ouverte sur ce poste, si elle existe encore."""
    return _recorded_image(record)


def remember_image(path: Path, record: Path = LAST_IMAGE_FILE) -> None:
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(str(Path(path).resolve()), encoding="utf-8")


def default_image() -> Path | None:
    """Image a ouvrir sans autre precision.

    `CRACK_IMAGE_PATH` si elle est definie, meme si le fichier manque : mieux
    vaut une erreur claire qu'une autre image ouverte en silence. Sinon la
    derniere image ouverte, puis la mosaique de reference.
    """
    chosen = os.environ.get("CRACK_IMAGE_PATH")
    if chosen:
        return Path(chosen)
    return last_image() or reference_image()


def reference_image(record: Path = REFERENCE_IMAGE_FILE) -> Path | None:
    """Mosaique de reference de ce poste, si elle est designee et presente.

    C'est celle dont les tuiles validees servent de verite terrain au banc et
    aux entrainements. On la designe par `CRACK_REFERENCE_IMAGE`, ou en
    ecrivant son chemin dans `data/image_reference.txt`.
    """
    chosen = os.environ.get("CRACK_REFERENCE_IMAGE")
    if chosen:
        return Path(chosen) if Path(chosen).is_file() else None
    return _recorded_image(record)


def benchmark_image() -> Path | None:
    """Image par defaut du banc et des entrainements : la reference, sinon la
    derniere ouverte."""
    return reference_image() or last_image()
