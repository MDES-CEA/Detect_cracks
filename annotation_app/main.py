"""API et application web de la visionneuse collaborative de fissures."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .backup import backup_database, start_periodic_backup
from .database import (
    AnnotationDatabase,
    CrackConflict,
    CRACK_CATEGORIES,
    CRACK_STATES,
    ZoneConflict,
    ZONE_STATUSES,
)
from .detection_service import CrackDetector
from .paths import APP_DIR, DATA_DIR, DEFAULT_DATABASE, default_image, remember_image
from .tile_service import PyramidTileService, TileNotFound


# Aucun chemin absolu : tout se deduit de l'emplacement du code (voir
# `paths.py`), ce qui permet de copier le dossier n'importe ou.
IMAGE_PATH = default_image()
if IMAGE_PATH is None or not IMAGE_PATH.is_file():
    raise RuntimeError(
        f"Mosaique introuvable : {IMAGE_PATH or 'aucune image choisie'}\n"
        "Lancer run_annotation_app.ps1, qui propose de la choisir, ou "
        "definir CRACK_IMAGE_PATH."
    )
IMAGE_PATH = IMAGE_PATH.resolve()
DATABASE_PATH = Path(os.environ.get("CRACK_DATABASE_PATH", DEFAULT_DATABASE)).resolve()
CACHE_DIR = Path(
    os.environ.get("CRACK_CACHE_DIR", DATA_DIR / "analysis_cache")
).resolve()
ZONE_SIZE = 2000

# Sauvegardes a cote de la base, sauf si `CRACK_BACKUP_DIR` designe un autre
# disque — le mieux, puisqu'une copie sur le meme disque ne protege pas d'une
# panne de celui-ci.
BACKUP_DIR = Path(
    os.environ.get("CRACK_BACKUP_DIR", DATABASE_PATH.parent / "sauvegardes")
).resolve()

# Avant toute ecriture dans la base, y compris l'enregistrement de l'image.
try:
    saved = backup_database(DATABASE_PATH, BACKUP_DIR)
    if saved:
        print(f"Sauvegarde       : {saved}", flush=True)
except Exception as error:
    print(f"ATTENTION, sauvegarde impossible dans {BACKUP_DIR} : {error}", flush=True)
start_periodic_backup(DATABASE_PATH, BACKUP_DIR)

database = AnnotationDatabase(DATABASE_PATH)
tiles = PyramidTileService(IMAGE_PATH)

# Identifiant de la mosaïque DANS la base : c'est lui qui sépare les tracés de
# deux images. `CRACK_IMAGE_ID` permet de le forcer ; sinon il est déduit du
# fichier (voir `resolve_image_id`), et `initialize_image` refuse de toute
# façon de rattacher une image à l'identifiant d'une autre.
IMAGE_ID = os.environ.get("CRACK_IMAGE_ID")
if not IMAGE_ID:
    IMAGE_ID, note = database.resolve_image_id(IMAGE_PATH, tiles.width, tiles.height)
    if note:
        print(note, flush=True)
database.initialize_image(
    IMAGE_ID, IMAGE_PATH, tiles.width, tiles.height, ZONE_SIZE
)
# Le prochain lancement sans argument rouvrira celle-ci. Seulement pour la base
# de travail : les tests sur copie ne doivent pas changer l'image de l'utilisateur.
if "CRACK_DATABASE_PATH" not in os.environ:
    remember_image(IMAGE_PATH)
detector = CrackDetector(tiles)

app = FastAPI(title="Annotation collaborative des fissures", version="0.4.0")
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

from .analysis_api import create_router
analysis_router = create_router(database, IMAGE_ID, detector, CACHE_DIR)
app.include_router(analysis_router)


class ZoneUpdate(BaseModel):
    status: str
    assigned_to: str | None = Field(default=None, max_length=80)
    expected_revision: int = Field(ge=0)


class DetectRequest(BaseModel):
    annotator: str | None = Field(default=None, max_length=80)


class CrackCreate(BaseModel):
    anchors: list[tuple[float, float]] = Field(min_length=2, max_length=100)
    annotator: str | None = Field(default=None, max_length=80)


class CrackUpdate(BaseModel):
    expected_revision: int = Field(ge=0)
    anchors: list[tuple[float, float]] | None = Field(
        default=None, min_length=2, max_length=100
    )
    category: str | None = None
    state: str | None = None
    annotator: str | None = Field(default=None, max_length=80)


def validate_anchors(zone: dict, anchors: list[tuple[float, float]]) -> list[list[float]]:
    result = []
    for x, y in anchors:
        if not (zone["x"] <= x < zone["x"] + zone["width"]):
            raise HTTPException(status_code=422, detail="Un point sort de la zone en x.")
        if not (zone["y"] <= y < zone["y"] + zone["height"]):
            raise HTTPException(status_code=422, detail="Un point sort de la zone en y.")
        result.append([round(float(x), 2), round(float(y), 2)])
    return result


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(APP_DIR / "static" / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "image": IMAGE_PATH.name, "database": str(DATABASE_PATH)}


@app.get("/api/image")
def image_metadata() -> dict:
    return {**tiles.metadata(), "id": IMAGE_ID, "zone_size": ZONE_SIZE}


@app.get("/api/tiles/{level}/{tile_x}/{tile_y}.png")
def image_tile(level: int, tile_x: int, tile_y: int, v: str | None = None) -> Response:
    try:
        content = tiles.tile_png(level, tile_x, tile_y)
    except TileNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return Response(
        content=content,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400, immutable" if v == tiles.cache_key else "no-store"},
    )


@app.get("/api/zones")
def zones() -> list[dict]:
    return database.list_zones(IMAGE_ID)


@app.get("/api/statistics/lengths")
def length_statistics(zone_id: int | None = Query(default=None)) -> dict:
    zone = None
    if zone_id is not None:
        try:
            zone = database.get_zone(IMAGE_ID, zone_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Zone introuvable") from error
    def summary(selected_id=None):
        result = analysis_router.measure_report(selected_id, False)
        result['length_px']['total'] = result['total_px']
        result['crack_count'] = {'total': result['raw_trace_count']}
        result.pop('segments', None)
        return result
    return {'unit':'px','image':summary(), 'zone':summary(zone_id) if zone else None}


@app.get("/api/cracks")
def image_cracks() -> list[dict]:
    """Géométries actives de toute la mosaïque pour la couche globale."""
    return [
        {
            "id": crack["id"],
            "zone_id": crack["zone_id"],
            "geometry": crack["geometry"],
            "category": crack["category"],
            "state": crack["state"],
        }
        for crack in database.list_image_cracks(IMAGE_ID)
    ]


@app.patch("/api/zones/{zone_id}")
def update_zone(zone_id: int, change: ZoneUpdate) -> dict:
    if change.status not in ZONE_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Statut attendu : {', '.join(ZONE_STATUSES)}",
        )
    try:
        return database.update_zone(
            IMAGE_ID,
            zone_id,
            change.status,
            change.assigned_to,
            change.expected_revision,
        )
    except ZoneConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Zone introuvable") from error


@app.get("/api/zones/{zone_id}/cracks")
def cracks(
    zone_id: int,
    include_rejected: bool = Query(default=False),
) -> list[dict]:
    try:
        database.get_zone(IMAGE_ID, zone_id)
        return database.list_cracks(IMAGE_ID, zone_id, include_rejected)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Zone introuvable") from error


@app.post("/api/zones/{zone_id}/prepare")
def prepare_zone(zone_id: int) -> dict:
    """Prechauffe silencieusement le routage quand l'humain choisit une zone."""
    try:
        zone = database.get_zone(IMAGE_ID, zone_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Zone introuvable") from error

    analysis = detector.prepare_route(zone)
    return {
        "ready": True,
        "diagnostics": analysis.diagnostics,
    }


@app.post("/api/zones/{zone_id}/detect")
def detect_cracks(zone_id: int, request: DetectRequest) -> dict:
    try:
        zone = database.get_zone(IMAGE_ID, zone_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Zone introuvable") from error

    # Ne jamais recalculer par-dessus une correction humaine, meme si tous les
    # anciens traces sont actuellement marques comme faux positifs.
    existing = database.list_cracks(IMAGE_ID, zone_id, include_rejected=False)
    if existing:
        return {
            "created": False,
            "cracks": existing,
            "diagnostics": {"message": "Travail existant conserve."},
        }

    # Si les couches de cette tuile ont deja ete calculees, les propositions
    # y sont deja : les relire evite de relancer le reseau pour rien.
    cached = analysis_router.layers.cached_proposals(zone)
    if cached is not None:
        cracks, diagnostics = cached
    else:
        analysis = detector.analyze(zone)
        cracks, diagnostics = analysis.cracks, analysis.diagnostics
    saved, created = database.add_detected_cracks_if_empty(
        IMAGE_ID, zone_id, cracks, request.annotator
    )
    return {
        "created": created,
        "cracks": saved,
        "diagnostics": diagnostics,
    }


@app.get("/api/zones/{zone_id}/analysis-map.png")
def analysis_map(zone_id: int, kind: str = Query(default="cost")) -> Response:
    if kind not in {"cost", "score", "mask", "skeleton"}:
        raise HTTPException(status_code=422, detail="Vue d'analyse inconnue.")
    try:
        zone = database.get_zone(IMAGE_ID, zone_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Zone introuvable") from error
    content = detector.analysis_map_png(zone, kind)
    return Response(
        content=content,
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/zones/{zone_id}/cracks", status_code=201)
def create_crack(zone_id: int, request: CrackCreate) -> dict:
    try:
        zone = database.get_zone(IMAGE_ID, zone_id)
        anchors = validate_anchors(zone, request.anchors)
        geometry = detector.route(zone, anchors)
        return database.create_crack(
            IMAGE_ID, zone_id, anchors, geometry, request.annotator
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Zone introuvable") from error


@app.patch("/api/cracks/{crack_id}")
def update_crack(crack_id: int, change: CrackUpdate) -> dict:
    if change.category is not None and change.category not in CRACK_CATEGORIES:
        raise HTTPException(
            status_code=422,
            detail=f"Categorie attendue : {', '.join(CRACK_CATEGORIES)}",
        )
    if change.state is not None and change.state not in CRACK_STATES:
        raise HTTPException(
            status_code=422,
            detail=f"Etat attendu : {', '.join(CRACK_STATES)}",
        )
    try:
        current = database.get_crack(IMAGE_ID, crack_id)
        zone = database.get_zone(IMAGE_ID, current["zone_id"])
        if change.anchors is None:
            anchors = current["anchors"]
            geometry = current["geometry"]
        else:
            anchors = validate_anchors(zone, change.anchors)
            geometry = detector.route(zone, anchors)
        return database.update_crack(
            IMAGE_ID,
            crack_id,
            change.expected_revision,
            anchors,
            geometry,
            change.category or current["category"],
            change.state or current["state"],
            change.annotator,
        )
    except CrackConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Fissure introuvable") from error
