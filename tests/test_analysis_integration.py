import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

import numpy as np
from PIL import Image
from annotation_app.analysis_api import create_router
from annotation_app.analysis_service import AnalysisLayers


class FakeDatabase:
    def list_zones(self, image_id):
        return [dict(id=1,x=0,y=0,width=20,height=20,status='done'),
                dict(id=2,x=20,y=0,width=20,height=20,status='todo')]

    def list_image_cracks(self, image_id):
        return [dict(id=1,zone_id=1,category='open',state='active',geometry=[[0,0],[10,0]]),
                dict(id=2,zone_id=2,category='filled',state='active',geometry=[[20,0],[30,0]])]


class AnalysisIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.folder=TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        source=Path(self.folder.name)/'image.tif'
        source.write_bytes(b'source fingerprint')
        values=np.eye(20,dtype=np.float32)
        tiles=SimpleNamespace(image_path=source,width=40,height=20,source=SimpleNamespace(direct=False))
        self.calls=0
        def analyze(zone):
            self.calls+=1
            return SimpleNamespace(score=values,cost=values,mask=values>0,skeleton=values>0,
                                   scale=1,cracks=[{'geometry':[[zone['x'],0],[zone['x']+19,19]]}])
        self.detector=SimpleNamespace(tiles=tiles,max_analysis_side=1000,analyze=analyze,
                                     prepare_route=lambda zone:SimpleNamespace(cost=values))
        router=create_router(FakeDatabase(),'test',self.detector,Path(self.folder.name)/'api')
        self.routes={route.path:route.endpoint for route in router.routes}

    def test_validated_filter_and_euclidean_exports(self):
        endpoint=self.routes['/api/analysis/lengths']
        self.assertEqual(endpoint(validated=True)['total_px'],10)
        self.assertEqual(endpoint(validated=False)['total_px'],20)
        self.assertEqual(endpoint(zone_id=2,validated=True)['total_px'],0)
        response=self.routes['/api/analysis/export.csv']()
        self.assertIn(b'open,10.0',response.body)
        for kind in ('lengths','orientation','map','spatial'):
            response=self.routes['/api/analysis/figure.{extension}']('png',kind=kind)
            self.assertEqual(Image.open(io.BytesIO(response.body)).format,'PNG')
        self.assertIn(b'<svg',self.routes['/api/analysis/figure.{extension}']('svg').body)
        self.assertTrue(self.routes['/api/analysis/figure.{extension}']('pdf').body.startswith(b'%PDF'))

    def test_persistent_arrays_and_transparent_unprocessed_area(self):
        layers=AnalysisLayers(self.detector,Path(self.folder.name)/'layers')
        zones=FakeDatabase().list_zones('test')
        layers.prepare(zones[0]); layers.prepare(zones[0])
        self.assertEqual(self.calls,1)
        another=AnalysisLayers(self.detector,Path(self.folder.name)/'layers')
        another.prepare(zones[0])
        self.assertEqual(self.calls,1)
        image=Image.open(io.BytesIO(layers.overview(zones,'skeleton')))
        self.assertEqual(image.getpixel((25,5))[3],0)
        self.assertEqual(image.getpixel((5,5))[3],255)
        for kind in layers.KINDS:
            self.assertEqual(Image.open(io.BytesIO(layers.png(zones[0],kind))).size,(20,20))

    def test_obsolete_caches_of_this_image_only_are_purged(self):
        root=Path(self.folder.name)/'purge'
        def folder(name, image=None, files=1):
            path=root/name; path.mkdir(parents=True)
            for index in range(files): (path/f'{index}.npz').write_bytes(b'x')
            if image: (path/'source.json').write_text(json.dumps({'image':str(image)}))
            return path
        source=self.detector.tiles.image_path
        old=folder('ancienne-version', source)
        empty=folder('vide', files=0)
        other=folder('autre-mosaique', Path(self.folder.name)/'autre.tif')
        unlabelled=folder('sans-etiquette')
        layers=AnalysisLayers(self.detector,root)
        self.assertFalse(old.exists())
        self.assertFalse(empty.exists())
        self.assertTrue(other.exists())
        self.assertTrue(unlabelled.exists())
        self.assertTrue((layers.directory/'source.json').exists())
        AnalysisLayers(self.detector,root)
        self.assertTrue(layers.directory.exists())

    def test_automatic_length_uses_final_geometry_and_reports_missing_tiles(self):
        endpoint=self.routes['/api/analysis/lengths']
        result=endpoint(source='automatic',validated=False)
        self.assertEqual(result['unprocessed_zone_ids'],[1,2])
        self.routes['/api/analysis/layers/{kind}.png']('centerline',zone_id=1)
        result=endpoint(source='automatic',validated=False)
        self.assertEqual(result['unprocessed_zone_ids'],[2])
        self.assertAlmostEqual(result['total_px'],19*2**.5)
        self.assertEqual(result['length_px']['unclassified'],result['total_px'])
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            self.routes['/api/analysis/export.csv'](source='automatic',validated=False)


if __name__=='__main__':
    unittest.main()
