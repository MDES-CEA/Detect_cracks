"""Read-only real-data validation; writes reports under validation/sorties/."""
import json
import sqlite3
from pathlib import Path
import subprocess
import sys
import torch

ROOT = Path(__file__).resolve().parent.parent
output = Path(__file__).resolve().parent/'sorties'
output.mkdir(exist_ok=True)
connection = sqlite3.connect(f'file:{ROOT / "annotation_app/data/annotations.sqlite3"}?mode=ro', uri=True)
trained = torch.load(ROOT/'annotation_app/modeles/crack_unet_holdout.pt', map_location='cpu', weights_only=False)['trained_zone_ids']
zones = [r[0] for r in connection.execute("SELECT id FROM zones WHERE status='done'") if r[0] not in trained]
print('Held-out validated zones:', zones, flush=True)
subprocess.run([sys.executable, str(ROOT/'evaluate_crack_detection.py'), '--model',
                str(ROOT/'annotation_app/modeles/crack_unet_holdout.pt'), '--zones', *map(str,zones),
                '--json', str(output/'holdout.json')], check=True)

