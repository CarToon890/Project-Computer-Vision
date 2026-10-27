"""Regression for real clipped-edge photos plus registered-row safety checks."""
import csv
import sys
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

import numpy as np
import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import omr_geometry as geometry


class GeometryTests(unittest.TestCase):
    def test_cnn_and_cla_share_the_same_locally_straightened_row(self):
        gray=np.full((100,180),255,np.uint8)
        points=[(35.+i*23,35.+i*3) for i in range(5)]
        for x,y in points:cv2.circle(gray,(round(x),round(y)),7,0,-1)
        row,local=geometry.straight_row_view(gray,points)
        self.assertLess(float(np.ptp(np.asarray(local)[:,1])),.01)
        self.assertEqual(row.shape[0],29)
        grid=[points]*100
        with patch.object(geometry.reader,'score_options',wraps=geometry.reader.score_options) as score:
            values=geometry.bubble_scores(gray,1,grid)
            np.testing.assert_array_equal(score.call_args[0][0],row)
        self.assertTrue((values>.2).all())
        expected=cv2.resize(row,(160,32),interpolation=cv2.INTER_AREA)
        np.testing.assert_array_equal(geometry.row_crop(gray,1,grid),expected)

    def test_camera_perspective_is_warped_before_both_readers_get_crops(self):
        canonical=np.full((1333,1000),255,np.uint8)
        centers=[]
        for col in range(4):
            for row in range(25):
                points=[(210.+col*181+opt*23,360.+row*26+(row//5)*15) for opt in range(5)]
                for x,y in points:cv2.circle(canonical,(round(x),round(y)),7,0,-1)
                centers.append(points)
        plane=np.float32([[0,0],[999,0],[999,1332],[0,1332]])
        camera=np.float32([[180,110],[880,235],[985,1220],[40,1100]])
        matrix=cv2.getPerspectiveTransform(plane,camera)
        photographed=cv2.warpPerspective(canonical,matrix,(1000,1333),borderValue=255)
        projected=cv2.perspectiveTransform(np.asarray(centers,np.float32).reshape(-1,1,2),matrix).reshape(100,5,2).tolist()
        with patch.object(geometry.reader,'register_form',return_value=(photographed,projected,{'mode':'synthetic-camera'})):
            corrected,points,info=geometry.rectify_sheet(cv2.cvtColor(photographed,cv2.COLOR_GRAY2BGR))
        grid=np.asarray(points).reshape(4,25,5,2)
        for row in range(25):
            self.assertLess(float(np.ptp(grid[:,row,:,1])),2.,'A camera image must become horizontal before CNN/CLA sampling.')
        dark=sum(float(corrected[round(y)-2:round(y)+3,round(x)-2:round(x)+3].mean())<70 for choice in points for x,y in choice)
        self.assertGreater(dark,475,'Warp source pixels as well as centers; do not invent corrected coordinates.')
        self.assertTrue(info['perspective_corrected'])

    def test_zero_homography_inliers_report_failure_instead_of_opencv_crash(self):
        keys=[SimpleNamespace(pt=(float(i*10),float(i*20))) for i in range(45)]
        matches=[[SimpleNamespace(queryIdx=i,trainIdx=i,distance=.1),SimpleNamespace(distance=1.)] for i in range(45)]
        with patch.object(geometry.cv2,'SIFT_create') as sift,patch.object(geometry.cv2,'BFMatcher') as matcher,patch.object(geometry,'train_references',return_value=[('S0001',[],keys,np.ones((45,128),np.float32))]),patch.object(geometry.cv2,'findHomography',return_value=(np.eye(3),np.zeros((45,1),np.uint8))):
            sift.return_value.detectAndCompute.return_value=(keys,np.ones((45,128),np.float32))
            matcher.return_value.knnMatch.return_value=matches
            with self.assertRaisesRegex(ValueError,'No spatially supported'):
                geometry.train_form_fallback(np.full((1333,1000),255,np.uint8),'S0002')

    def test_direct_grid_without_two_bottom_markers_is_not_accepted(self):
        centers=[[(200.+j*22,350.+i*7) for j in range(5)] for i in range(100)]
        with patch.object(geometry.reader,'register_form',side_effect=ValueError('No markers')),patch.object(geometry.reader,'locate_grid',return_value=centers),patch.object(geometry.reader,'components',return_value=[]),patch.object(geometry,'paper_candidates',return_value=[]),patch.object(geometry,'train_form_fallback',side_effect=ValueError('No spatially supported form')):
            with self.assertRaisesRegex(ValueError,'No spatially supported'):
                geometry.rectify_sheet(np.full((1333,1000,3),255,np.uint8))

    def test_real_distant_and_clipped_forms_register_all_rows(self):
        path = ROOT / 'data/metadata/image_inventory_verified.csv'
        if not path.exists():
            self.skipTest('Private source images are intentionally not committed.')
        with path.open(encoding='utf-8-sig',newline='') as f:
            inventory=list(csv.DictReader(f))
        for sid,role in [('S0042','B'),('S0102','A'),('S0106','A')]:
            with self.subTest(sheet=sid,role=role):
                row=next(r for r in inventory if r['sheet_id']==sid and r['capture_role']==role and r['pair_status']=='verified')
                raw=geometry.read_image(ROOT/row['relative_path'],{},ROOT)
                gray,centers,info=geometry.rectify_sheet(raw,source_sheet_id=sid)
                self.assertEqual(len(centers),100)
                self.assertTrue(all(len(points)==5 for points in centers))
                for q in (1,25,26,50,51,75,76,100):
                    self.assertEqual(geometry.row_crop(gray,q,centers).shape,(32,160))

    def test_real_background_corner_does_not_steal_the_upper_marker(self):
        mapping=ROOT/'data/metadata/heic_conversion_map.csv'
        if not mapping.exists():
            self.skipTest('Private normalized photos are not committed.')
        with mapping.open(encoding='utf-8-sig',newline='') as f:
            conversions={r['source_relative_path']:r['normalized_relative_path'] for r in csv.DictReader(f)}
        with (ROOT/'data/metadata/image_inventory_verified.csv').open(encoding='utf-8-sig',newline='') as f:
            inventory=list(csv.DictReader(f))
        for sid in ('S0133','S0145','S0146','S0156','S0158','S0188','S0192','S0196','S0263','S0268','S0289','S0290'):
            with self.subTest(sheet=sid):
                row=next(r for r in inventory if r['sheet_id']==sid and r['capture_role']=='B' and r['pair_status']=='verified')
                raw=geometry.read_image(ROOT/row['relative_path'],conversions,ROOT)
                gray,centers,info=geometry.rectify_sheet(raw,source_sheet_id=sid)
                self.assertEqual(len(centers),100)
                self.assertTrue(all(len(points)==5 for points in centers))

    def test_invalid_or_incomplete_registration_never_yields_guessed_rows(self):
        with self.assertRaises(ValueError):
            geometry.rectify_sheet(None)
        image = np.full((1333, 1000, 3), 255, dtype=np.uint8)
        with patch.object(geometry.reader, 'register_form', return_value=(image[:, :, 0], [], {})):
            with self.assertRaises(ValueError):
                geometry.rectify_sheet(image)
        with self.assertRaises(ValueError):
            geometry.question_centers([], 1)

    def test_real_s0001_without_detectable_outer_boundary_is_registered(self):
        path = ROOT / 'data/metadata/image_inventory_verified.csv'
        if not path.exists():
            self.skipTest('Local source images are intentionally not committed.')
        with path.open(encoding='utf-8-sig', newline='') as f:
            row = next(r for r in csv.DictReader(f) if r['sheet_id'] == 'S0001' and r['capture_role'] == 'A')
        raw = geometry.read_image(ROOT / row['relative_path'], {}, ROOT)
        gray, centers, registration = geometry.rectify_sheet(raw)
        self.assertEqual(len(centers), 100)
        self.assertTrue(registration['mode'])
        for question in (1, 26, 51, 76, 100):
            self.assertEqual(geometry.row_crop(gray, question, centers).shape, (32, 160))
            self.assertEqual(geometry.bubble_scores(gray, question, centers).shape, (5,))

    def test_real_s0002_uses_another_train_form_without_its_own_b(self):
        path = ROOT / 'data/metadata/image_inventory_verified.csv'
        if not path.exists():
            self.skipTest('Local source images are intentionally not committed.')
        with path.open(encoding='utf-8-sig', newline='') as f:
            row = next(r for r in csv.DictReader(f) if r['sheet_id'] == 'S0002' and r['capture_role'] == 'A')
        raw = geometry.read_image(ROOT / row['relative_path'], {}, ROOT)
        gray, centers, registration = geometry.rectify_sheet(raw, source_sheet_id='S0002')
        self.assertEqual(registration['mode'], 'train-form-homography')
        self.assertNotEqual(registration['reference_sheet'], 'S0002')
        self.assertGreaterEqual(registration['inliers'], 40)
        self.assertGreaterEqual(registration['coverage'], .35)
        self.assertEqual(geometry.row_crop(gray, 100, centers).shape, (32, 160))


if __name__ == '__main__':
    unittest.main()
