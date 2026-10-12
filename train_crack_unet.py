"""Entraîne le réseau de segmentation des fissures sur les tuiles validées.

Motivation mesurée : le modèle par pixel décide à partir de dix descripteurs
locaux et ne voit aucune forme, d'où un masque qui allume 6,4 % de l'image pour
un couloir de fissures qui en représente 1 à 2 %. Toute la chaîne aval passe
ensuite son temps à jeter ce bruit, et y perd un tiers du rappel.

Usage :

    python train_crack_unet.py --steps 3000
    python train_crack_unet.py --exclude-zones 6 11 14 ...   # test honnête

Comme pour `train_crack_detector.py`, seules la présence et la position des
tracés servent de cible ; les catégories ne sont jamais utilisées.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from time import perf_counter

import numpy as np
from scipy.ndimage import binary_dilation
from skimage.draw import line as draw_line

import crack_length_analysis_multi as base
from annotation_app.detection_service import CrackDetector
from annotation_app.paths import DEFAULT_DATABASE, benchmark_image
from annotation_app.tile_service import PyramidTileService
from annotation_app.unet_model import DEFAULT_UNET_PATH, build_network, prepare_inputs


# La mosaique de reference si elle est la, sinon la derniere ouverte.
DEFAULT_IMAGE = benchmark_image()


def target_mask(polylines, shape, zone, scale) -> np.ndarray:
    """Rasterise les tracés humains, épaissis d'un pixel d'analyse.

    À l'échelle 2 la cible fait donc environ 6 px pleine résolution, soit
    l'ordre de grandeur d'une fissure plus la marge de pointage humaine.
    """
    mask = np.zeros(shape, dtype=bool)
    for points in polylines:
        points = np.asarray(points, dtype=float)
        rows = (points[:, 1] - zone["y"]) / scale
        cols = (points[:, 0] - zone["x"]) / scale
        for first_row, first_col, second_row, second_col in zip(
            rows, cols, rows[1:], cols[1:]
        ):
            rr, cc = draw_line(
                int(round(first_row)), int(round(first_col)),
                int(round(second_row)), int(round(second_col)),
            )
            valid = (rr >= 0) & (cc >= 0) & (rr < shape[0]) & (cc < shape[1])
            mask[rr[valid], cc[valid]] = True
    return binary_dilation(mask, structure=np.ones((3, 3)))


def load_tiles(connection, detector, zones) -> list[dict]:
    tiles = []
    for index, zone in enumerate(zones, start=1):
        polylines = [
            json.loads(row["geometry_json"])
            for row in connection.execute(
                "SELECT geometry_json FROM cracks "
                "WHERE zone_id=? AND state!='rejected'",
                (zone["id"],),
            )
        ]
        gray, scale = detector._read_reduced(zone)
        ridge, _ = base.build_cost_image(gray.astype(np.float32) / 255.0)
        target = target_mask(polylines, gray.shape, zone, scale)
        tiles.append({
            "id": int(zone["id"]),
            "inputs": prepare_inputs(gray, ridge).astype(np.float16),
            "target": target,
            "crack_pixels": np.argwhere(target).astype(np.int32),
        })
        print(f"[{index}/{len(zones)}] tuile {zone['id']} : "
              f"{int(target.sum()):>7} px de fissure", flush=True)
    return tiles


def sample_patch(tile, size, rng):
    """Une imagette, centrée 4 fois sur 5 sur un pixel de fissure."""
    height, width = tile["target"].shape
    points = tile["crack_pixels"]
    if len(points) and rng.random() < 0.8:
        row, col = points[rng.integers(len(points))]
        row = int(row) - size // 2 + int(rng.integers(-size // 4, size // 4 + 1))
        col = int(col) - size // 2 + int(rng.integers(-size // 4, size // 4 + 1))
    else:
        row = int(rng.integers(0, max(1, height - size)))
        col = int(rng.integers(0, max(1, width - size)))
    row = max(0, min(row, height - size))
    col = max(0, min(col, width - size))
    inputs = tile["inputs"][:, row:row + size, col:col + size].astype(np.float32)
    target = tile["target"][row:row + size, col:col + size].astype(np.float32)

    turns = int(rng.integers(4))
    if turns:
        inputs = np.rot90(inputs, turns, axes=(1, 2))
        target = np.rot90(target, turns)
    if rng.random() < 0.5:
        inputs, target = inputs[:, ::-1], target[::-1]
    if rng.random() < 0.5:
        inputs, target = inputs[:, :, ::-1], target[:, ::-1]
    return np.ascontiguousarray(inputs), np.ascontiguousarray(target)


def batch(tiles, size, count, rng):
    pairs = [sample_patch(tiles[rng.integers(len(tiles))], size, rng)
             for _ in range(count)]
    inputs = np.stack([pair[0] for pair in pairs])
    targets = np.stack([pair[1] for pair in pairs])[:, None]
    return inputs, targets


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE,
                        required=DEFAULT_IMAGE is None)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output", type=Path, default=DEFAULT_UNET_PATH)
    parser.add_argument("--exclude-zones", type=int, nargs="*", default=None,
                        help="Tuiles réservées à la validation et jamais apprises")
    parser.add_argument("--steps", type=int, default=3000)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--patch", type=int, default=256)
    parser.add_argument("--base", type=int, default=16)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--seed", type=int, default=287298)
    args = parser.parse_args()

    import torch
    from torch.nn import functional

    torch.manual_seed(args.seed)
    rng = np.random.default_rng(args.seed)
    print(f"torch {torch.__version__}, {torch.get_num_threads()} threads")

    connection = sqlite3.connect(args.database)
    connection.row_factory = sqlite3.Row
    zones = [dict(row) for row in connection.execute(
        "SELECT * FROM zones WHERE status='done' ORDER BY id")]
    detector = CrackDetector(
        PyramidTileService(args.image), max_analysis_side=1000, model_path=None)

    excluded = set(args.exclude_zones or [])
    print(f"Préparation de {len(zones)} tuiles...")
    tiles = load_tiles(connection, detector, zones)
    training = [tile for tile in tiles
                if tile["id"] not in excluded and len(tile["crack_pixels"])]
    validation = [tile for tile in tiles
                  if tile["id"] in excluded and len(tile["crack_pixels"])]
    if not validation:
        # Sans exclusion demandee, on garde quand meme de quoi surveiller la
        # convergence, mais les chiffres seront alors optimistes.
        validation = training[::6]
        print("Aucune tuile exclue : la validation recoupe l'apprentissage.")
    print(f"{len(training)} tuiles apprises, {len(validation)} en validation")

    positive = sum(int(tile["target"].sum()) for tile in training)
    total = sum(tile["target"].size for tile in training)
    pos_weight = float(min(20.0, (total - positive) / max(positive, 1)))
    print(f"Fissures : {100 * positive / total:.2f} % des pixels, "
          f"pos_weight {pos_weight:.1f}")

    network = build_network(in_channels=2, base=args.base)
    parameters = sum(p.numel() for p in network.parameters())
    print(f"Réseau : {parameters:,} paramètres")
    optimiser = torch.optim.AdamW(network.parameters(), lr=args.lr, weight_decay=1e-4)
    schedule = torch.optim.lr_scheduler.CosineAnnealingLR(optimiser, T_max=args.steps)
    weight = torch.tensor(pos_weight)

    def loss_of(logits, targets):
        entropy = functional.binary_cross_entropy_with_logits(
            logits, targets, pos_weight=weight)
        probability = torch.sigmoid(logits)
        overlap = (probability * targets).sum()
        dice = 1.0 - (2.0 * overlap + 1.0) / (
            probability.sum() + targets.sum() + 1.0)
        return entropy + dice

    fixed_validation = [batch(validation, args.patch, args.batch, np.random.default_rng(7))
                        for _ in range(8)]
    best = float("inf")
    started = perf_counter()
    network.train()
    for step in range(1, args.steps + 1):
        inputs, targets = batch(training, args.patch, args.batch, rng)
        logits = network(torch.from_numpy(inputs))
        loss = loss_of(logits, torch.from_numpy(targets))
        optimiser.zero_grad(set_to_none=True)
        loss.backward()
        optimiser.step()
        schedule.step()

        if step % 100 == 0 or step == 20:
            network.eval()
            with torch.no_grad():
                scores = [
                    float(loss_of(network(torch.from_numpy(a)), torch.from_numpy(b)))
                    for a, b in fixed_validation
                ]
            network.train()
            mean = float(np.mean(scores))
            marker = ""
            if mean < best:
                best = mean
                marker = "  <- meilleur"
                torch.save(
                    {
                        "state_dict": network.state_dict(),
                        "in_channels": 2,
                        "base": args.base,
                        "threshold": 0.5,
                        "max_analysis_side": 1000,
                        "trained_zone_ids": [tile["id"] for tile in training],
                        "features_version": "unet-1",
                    },
                    args.output,
                )
            rate = step / (perf_counter() - started)
            print(f"  pas {step:>5}/{args.steps}  apprentissage {loss.item():.4f}  "
                  f"validation {mean:.4f}  {rate:.2f} pas/s{marker}", flush=True)

    # Calibration du seuil sur les tuiles de validation, en pleine tuile.
    from annotation_app.unet_model import load_unet, unet_score

    artifact = load_unet(args.output)
    best_threshold, best_f1 = 0.5, -1.0
    probabilities, targets = [], []
    for tile in validation:
        inputs = tile["inputs"].astype(np.float32)
        with torch.no_grad():
            padded = np.pad(inputs, ((0, 0), (0, (-inputs.shape[1]) % 8),
                                     (0, (-inputs.shape[2]) % 8)), mode="reflect")
            logits = artifact["model"](torch.from_numpy(padded)[None])
            probability = torch.sigmoid(logits)[0, 0].numpy()
        probabilities.append(probability[:inputs.shape[1], :inputs.shape[2]].ravel())
        targets.append(tile["target"].ravel())
    probability = np.concatenate(probabilities)
    truth = np.concatenate(targets)
    sweep = np.concatenate([np.arange(0.10, 0.90, 0.05), np.arange(0.90, 0.996, 0.01)])
    for threshold in sweep:
        predicted = probability >= threshold
        hit = float((predicted & truth).sum())
        if not hit:
            continue
        precision = hit / predicted.sum()
        recall = hit / truth.sum()
        f1 = 2 * precision * recall / (precision + recall)
        print(f"  seuil {threshold:.2f} : precision {precision * 100:5.1f} %  "
              f"rappel {recall * 100:5.1f} %  F1 {f1 * 100:5.1f} %")
        if f1 > best_f1:
            best_threshold, best_f1 = float(threshold), f1

    checkpoint = torch.load(args.output, map_location="cpu", weights_only=False)
    checkpoint["threshold"] = best_threshold
    torch.save(checkpoint, args.output)
    print(f"Seuil retenu : {best_threshold:.2f} (F1 pixel {best_f1 * 100:.1f} %)")
    print(f"Réseau enregistré : {args.output}")


if __name__ == "__main__":
    main()
