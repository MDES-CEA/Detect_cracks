"""Réentraîne le repérage automatique depuis les tuiles validées."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

import joblib
import numpy as np
from scipy.ndimage import distance_transform_edt
from skimage.draw import line

from annotation_app.detector_model import (
    DEFAULT_MODEL_PATH,
    FEATURES_VERSION,
    pixel_features,
    train_model,
)
from annotation_app.detection_service import CrackDetector
from annotation_app.paths import DEFAULT_DATABASE, benchmark_image
from annotation_app.tile_service import PyramidTileService


# La mosaique de reference si elle est la, sinon la derniere ouverte.
DEFAULT_IMAGE = benchmark_image()


def target_distance(zone: dict, shape: tuple[int, int], scale: int, rows) -> np.ndarray:
    mask = np.zeros(shape, dtype=bool)
    for row_value in rows:
        points = np.asarray(json.loads(row_value["geometry_json"]), dtype=float)
        points[:, 0] = (points[:, 0] - zone["x"]) / scale
        points[:, 1] = (points[:, 1] - zone["y"]) / scale
        for first, second in zip(points, points[1:]):
            rr, cc = line(
                int(round(first[1])), int(round(first[0])),
                int(round(second[1])), int(round(second[0])),
            )
            valid = (rr >= 0) & (cc >= 0) & (rr < shape[0]) & (cc < shape[1])
            mask[rr[valid], cc[valid]] = True
    if not mask.any():
        return np.full(shape, 999.0)
    return distance_transform_edt(~mask)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE,
                        required=DEFAULT_IMAGE is None)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument(
        "--max-analysis-side", type=int, default=1000,
        help="Cote maximal de la tuile analysee. A 500, une tuile de 2000 px "
             "est reduite d'un facteur 4 et la largeur mediane d'une fissure, "
             "2 px, y tombe a 0,5 px (defaut : 1000)",
    )
    parser.add_argument(
        "--positive-distance", type=float, default=1.0,
        help="Distance au trace humain, EN PIXELS DE L'ANALYSE, en deca de "
             "laquelle un pixel est etiquete fissure. Trop large, la majorite "
             "des positifs est en realite de la matrice (defaut : 1)",
    )
    parser.add_argument(
        "--negative-distance", type=float, default=6.0,
        help="Distance au-dela de laquelle un pixel est etiquete matrice ; "
             "la bande intermediaire est ignoree (defaut : 6)",
    )
    parser.add_argument(
        "--threshold", type=float, default=0.70,
        help="Seuil haut d'hysteresis inscrit dans le modele (defaut : 0,70)",
    )
    parser.add_argument(
        "--exclude-zones", type=int, nargs="*", default=None,
        help="Identifiants de tuiles a NE PAS apprendre. Sert a mesurer la "
             "generalisation : sans exclusion, le banc mesure la performance "
             "sur les tuiles memes qui ont servi a l'apprentissage",
    )
    args = parser.parse_args()
    print(
        f"Analyse a {args.max_analysis_side} px de cote, positifs a "
        f"<= {args.positive_distance:g} px du trace, negatifs a "
        f">= {args.negative_distance:g} px"
    )

    connection = sqlite3.connect(args.database)
    connection.row_factory = sqlite3.Row
    zones = [dict(row) for row in connection.execute(
        "SELECT * FROM zones WHERE status = 'done' ORDER BY row_index, col_index"
    )]
    if args.exclude_zones:
        excluded = set(args.exclude_zones)
        zones = [zone for zone in zones if zone["id"] not in excluded]
        print(f"{len(excluded)} tuiles ecartees de l'apprentissage")
    if not zones:
        raise SystemExit("Aucune tuile validée disponible pour l'apprentissage.")

    detector = CrackDetector(
        PyramidTileService(args.image),
        max_analysis_side=args.max_analysis_side,
        model_path=None,
    )
    rng = np.random.default_rng(287298)
    training_features: list[np.ndarray] = []
    training_labels: list[np.ndarray] = []
    hard_negative_pools: list[tuple[np.ndarray, bool]] = []
    used_zone_ids: list[int] = []

    for index, zone in enumerate(zones, start=1):
        rows = connection.execute(
            """
            SELECT geometry_json FROM cracks
            WHERE zone_id = ? AND state != 'rejected'
            """,
            (zone["id"],),
        ).fetchall()
        gray, scale = detector._read_reduced(zone)
        values = pixel_features(gray)
        distances = target_distance(zone, gray.shape, scale, rows)
        positive = np.flatnonzero(distances.ravel() <= args.positive_distance)
        negative = np.flatnonzero(distances.ravel() >= args.negative_distance)
        if len(positive):
            positive = rng.choice(positive, min(6000, len(positive)), replace=False)
        negative_limit = 100000 if not len(positive) else 18000
        negative = rng.choice(negative, min(negative_limit, len(negative)), replace=False)
        hard_candidates = np.flatnonzero(distances.ravel() >= args.negative_distance)
        hard_candidates = rng.choice(
            hard_candidates, min(50000, len(hard_candidates)), replace=False
        )
        hard_negative_pools.append(
            (values.reshape(-1, values.shape[-1])[hard_candidates], not len(positive))
        )
        chosen = np.concatenate([positive, negative])
        training_features.append(values.reshape(-1, values.shape[-1])[chosen])
        training_labels.append(
            np.concatenate([np.ones(len(positive)), np.zeros(len(negative))])
        )
        used_zone_ids.append(zone["id"])
        print(f"[{index}/{len(zones)}] tuile {zone['id']} préparée")

    features = np.vstack(training_features)
    labels = np.concatenate(training_labels)
    if int(labels.sum()) < 100:
        raise SystemExit("Pas assez de tracés validés pour entraîner le détecteur.")
    print(f"Apprentissage sur {len(features):,} pixels, dont {int(labels.sum()):,} positifs")
    model = train_model(features, labels)
    hard_negatives: list[np.ndarray] = []
    for values, empty_tile in hard_negative_pools:
        probability = model.predict_proba(values)[:, 1]
        keep = min(20000 if empty_tile else 3000, len(values))
        hardest = np.argpartition(probability, -keep)[-keep:]
        hard_negatives.append(values[hardest])
    hard = np.vstack(hard_negatives)
    features = np.vstack([features, hard])
    labels = np.concatenate([labels, np.zeros(len(hard))])
    print(f"Second passage avec {len(hard):,} faux positifs difficiles")
    model = train_model(features, labels)
    artifact = {
        "model": model,
        "threshold": args.threshold,
        "max_analysis_side": args.max_analysis_side,
        "positive_distance": args.positive_distance,
        "features_version": FEATURES_VERSION,
        "trained_zone_ids": used_zone_ids,
        "positive_samples": int(labels.sum()),
        "total_samples": len(labels),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, args.output, compress=3)
    print(f"Modèle enregistré : {args.output}")


if __name__ == "__main__":
    main()
