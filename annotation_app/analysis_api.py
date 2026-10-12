from typing import Annotated
"""Read-only scientific analysis and exports, separate from annotation writes."""
import csv
import io
import json
import zipfile
import tempfile
from pathlib import Path
from threading import Lock

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response, FileResponse
from starlette.background import BackgroundTask
from .analysis_service import AnalysisLayers
from .length_analysis import measure, nearby_overlaps, CATEGORIES, LABELS, COLORS

plot_lock = Lock()


def create_router(database, image_id, detector, directory):
    router = APIRouter(prefix='/api/analysis')
    layers = AnalysisLayers(detector, directory)

    def selected(zone_id, validated):
        zones = database.list_zones(image_id)
        if zone_id is not None:
            zones = [z for z in zones if z['id'] == zone_id]
            if not zones:
                raise HTTPException(404, 'Zone introuvable')
        if validated:
            zones = [z for z in zones if z['status'] == 'done']
        ids = {z['id'] for z in zones}
        cracks = [c for c in database.list_image_cracks(image_id) if c['zone_id'] in ids]
        return zones, cracks

    def report(zone_id, validated, review=False, source='annotations', tolerance_px=2.):
        zones, cracks = selected(zone_id, validated)
        if source not in {'annotations', 'automatic'}:
            raise HTTPException(400, 'Source inconnue')
        missing = []
        if source == 'automatic':
            missing = [z['id'] for z in zones if not layers.path(z).exists()]
            zones = [z for z in zones if layers.path(z).exists()]
            cracks = layers.automatic_cracks(zones)
        result = measure(cracks, tolerance_px)
        result['validated_only'] = validated
        result['source'] = source
        result['unprocessed_zone_ids'] = missing
        from .overlap_measure import distribute_lengths
        zone_lengths = distribute_lengths(result['segments'], zones)
        result['zones'] = [{**{k: z[k] for k in ('id', 'x', 'y', 'width', 'height', 'status')},
                            'length_px': zone_lengths[z['id']]}
                           for z in zones]
        result['image'] = {'width': detector.tiles.width, 'height': detector.tiles.height}
        return result

    @router.get('/lengths')
    def lengths(zone_id: int | None = None, validated: bool = False, source: str = 'annotations', tolerance_px: Annotated[float, Query(ge=0, le=5)] = 2.):
        return report(zone_id, validated, source=source, tolerance_px=tolerance_px)

    @router.get('/layers/status')
    def status():
        zones = database.list_zones(image_id)
        with layers.job_lock:
            return {**layers.status,
                    'cached_zone_ids': [z['id'] for z in zones if layers.path(z).exists()],
                    # Change seulement quand une tuile est calculee. Sert de
                    # version dans l'URL de la couche d'ensemble : un
                    # horodatage y interdisait tout cache navigateur et
                    # relancait un rendu d'une seconde a chaque deplacement.
                    'layers_signature': layers.overview_signature(zones, 'centerline')}

    @router.post('/layers/prepare')
    def prepare(zone_id: int | None = None, validated: bool = False):
        zones, _ = selected(zone_id, validated)
        return layers.start(zones)

    @router.post('/layers/cancel')
    def cancel():
        layers.cancel.set()
        return {'cancellation_requested': True}

    @router.get('/layers/{kind}.png')
    def layer(kind: str, zone_id: int | None = None, exclude: str = '', validated: bool = False):
        if kind not in layers.KINDS:
            raise HTTPException(400, 'Couche inconnue')
        zones, _ = selected(zone_id, validated)
        if zone_id is not None and not zones:
            from PIL import Image
            output=io.BytesIO();Image.new('RGBA',(1,1)).save(output,format='PNG')
            return Response(output.getvalue(),media_type='image/png')
        if exclude and zone_id is None:
            try:
                excluded = {int(value) for value in exclude.split(',')}
            except ValueError as error:
                raise HTTPException(400, 'Liste de zones invalide') from error
            zones = [z for z in zones if z['id'] not in excluded]
        content = layers.png(zones[0], kind) if zone_id is not None else layers.overview(zones, kind)
        # L'URL porte deja la version des couches ; le navigateur peut donc la
        # garder, et un deplacement de la vue ne redemande plus rien.
        return Response(content, media_type='image/png',
                        headers={'Cache-Control': 'private, max-age=3600'})

    @router.get('/masks.zip')
    def masks(zone_id: int | None = None, validated: bool = False):
        zones, _ = selected(zone_id, validated)
        missing = [z['id'] for z in zones if not layers.path(z).exists()]
        if missing:
            raise HTTPException(409, f'{len(missing)} tuile(s) non calculée(s). Lancer ou reprendre le calcul des couches.')
        # The compressed arrays preserve the detector resolution, with explicit
        # source coordinates; no full-resolution width/area is inferred.
        with tempfile.NamedTemporaryFile(suffix='.zip', dir=layers.directory, delete=False) as temporary:
            export_path = Path(temporary.name)
        with zipfile.ZipFile(export_path, 'w') as archive:
            for zone in zones:
                archive.write(layers.path(zone), f"zone-{zone['id']}.npz")
            archive.writestr('metadata.json', json.dumps({
                'image': str(detector.tiles.image_path), 'cache_signature': layers.directory.name,
                'coordinates': 'Original image pixels, x right, y down; each array spans the specified zone.',
                'resolution': 'Native analysis resolution; not a physical crack width or area mask.',
                'layers': sorted(layers.KINDS),
                'zones': [{k:z[k] for k in ('id','x','y','width','height')} for z in zones]}, indent=2))
        return FileResponse(export_path, media_type='application/zip', filename='analysis-masks.zip',
                            background=BackgroundTask(export_path.unlink, missing_ok=True))

    @router.get('/export.csv')
    def export_csv(zone_id: int | None = None, validated: bool = False, source: str = 'annotations', tolerance_px: Annotated[float, Query(ge=0, le=5)] = 2.):
        result = report(zone_id, validated, source=source, tolerance_px=tolerance_px)
        if result['unprocessed_zone_ids']:
            raise HTTPException(409, 'Calculer toutes les couches du périmètre avant cet export automatique.')
        output = io.StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow(['category', 'length_px', 'x1', 'y1', 'x2', 'y2', 'validated_only', 'source', 'unprocessed_zones','tolerance_px'])
        for segment in result['segments']:
            writer.writerow([segment['category'], segment['length_px'], *segment['geometry'][0], *segment['geometry'][1], validated, source, len(result['unprocessed_zone_ids']),tolerance_px])
        return Response(output.getvalue().encode('utf-8-sig'), media_type='text/csv',
                        headers={'Content-Disposition': 'attachment; filename="centerlines.csv"'})

    @router.get('/figure.{extension}')
    def figure(extension: str, kind: str = 'lengths', zone_id: int | None = None,
               validated: bool = False, background: bool = True, source: str = 'annotations', tolerance_px: Annotated[float, Query(ge=0, le=5)] = 2.):
        if extension not in {'png', 'svg', 'pdf'} or kind not in {'lengths', 'orientation', 'map', 'spatial'}:
            raise HTTPException(400, 'Format ou figure inconnu')
        result = report(zone_id, validated, source=source, tolerance_px=tolerance_px)
        if source == 'automatic' and not result['zones']:
            raise HTTPException(409, 'Aucune tuile calculée dans le périmètre.')
        with plot_lock:
            from matplotlib.figure import Figure
            from matplotlib.collections import LineCollection
            from matplotlib.patches import Rectangle, Patch
            fig = Figure(figsize=(7, 9) if kind in {'map','spatial'} else (9, 6), layout='constrained')
            ax = fig.subplots()
            if kind == 'lengths':
                ax.bar(LABELS, [result['length_px'][c] for c in CATEGORIES], color=COLORS)
                ax.set_ylabel('Longueur centrale unique (px)')
                ax.tick_params(axis='x', rotation=20)
            elif kind == 'orientation':
                ax.bar(range(0, 180, 10), result['orientation_length_px'], width=10, align='edge')
                ax.set_xlabel('Orientation (°), 0 = horizontal ; axe y image vers le bas')
                ax.set_ylabel('Longueur centrale unique (px)')
            else:
                zones = result['zones']
                x0, y0, x1, y1 = 0, 0, detector.tiles.width, detector.tiles.height
                if zone_id is not None:
                    original, _ = selected(zone_id, False)
                    z = original[0]
                    x0, y0, x1, y1 = z['x'], z['y'], z['x']+z['width'], z['y']+z['height']
                if background:
                    # Bounded preview sampled directly from the mapped source.
                    image_source = detector.tiles.source
                    step = max(1, int(max(x1-x0, y1-y0)/1800))
                    if image_source.direct:
                        import numpy as np
                        pixels = np.asarray(image_source._memmap[y0:y1:step, x0:x1:step])
                        if image_source._lut is not None:
                            pixels = image_source._lut[pixels]
                        ax.imshow(pixels, cmap='gray', vmin=0, vmax=255, extent=(x0, x1, y1, y0))
                if kind == 'map':
                    for cat, color in zip(CATEGORIES, COLORS):
                        ax.add_collection(LineCollection([s['geometry'] for s in result['segments'] if s['category'] == cat], colors=color, linewidths=1))
                    ax.legend(handles=[Patch(color=c, label=l) for c,l in zip(COLORS, LABELS)], loc='upper left', bbox_to_anchor=(1.02,1), fontsize=8)
                else:
                    from matplotlib.colors import Normalize
                    from matplotlib.cm import ScalarMappable
                    norm = Normalize(0, max([z['length_px'] for z in zones]+[1]))
                    cmap = __import__('matplotlib').colormaps['viridis']
                    for z in zones:
                        ax.add_patch(Rectangle((z['x'], z['y']), z['width'], z['height'], facecolor=cmap(norm(z['length_px'])), alpha=.85))
                    fig.colorbar(ScalarMappable(norm=norm, cmap=cmap), ax=ax, label='Longueur centrale unique par tuile (px)')
                ax.set(xlim=(x0,x1), ylim=(y1,y0), xlabel='x (px)', ylabel='y (px)', aspect='equal')
            ax.set_title(('Axes automatiques non validés' if source == 'automatic' else 'Lignes centrales annotées')+' · '+('zones validées' if validated else 'toutes les zones'))
            if result['unprocessed_zone_ids']:
                ax.set_title(ax.get_title()+f"\nCouverture partielle : {len(result['unprocessed_zone_ids'])} tuile(s) non calculée(s)")
            fig.supxlabel(f'Superpositions parallèles comptées une fois (tolérance {tolerance_px:g} px).\n'
                          f'{result["raw_trace_count"]} tracés enregistrés ; désaccords de catégorie = Conflit.',
                          fontsize=8)
            output = io.BytesIO()
            fig.savefig(output, format=extension, dpi=200)
        return Response(output.getvalue(), media_type={'png':'image/png','svg':'image/svg+xml','pdf':'application/pdf'}[extension],
                        headers={'Content-Disposition': f'inline; filename="centerlines-{kind}.{extension}"'})

    router.measure_report = report
    router.layers = layers
    return router
