"""Check provisional classification and fail-closed form registration."""
import sys
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from build_answer_pilot import align_markers, classify, locate_grid
import build_answer_pilot as reader


class PilotReaderTests(unittest.TestCase):
    def test_single_missing_dash_requires_a_unique_regular_block_fit(self):
        y=360+24*(np.arange(25)+.8*(np.arange(25)//5))
        points=np.column_stack((150+.02*y,y))
        restored=reader.complete_marker_rail(np.delete(points,4,axis=0))
        np.testing.assert_allclose(restored,points,atol=.01)
        self.assertEqual(len(reader.complete_marker_rail(points[:23])),23)
        noise=np.column_stack((np.full(24,150.),np.random.default_rng(2).uniform(100,1200,24)))
        noise=noise[np.argsort(noise[:,1])]
        self.assertEqual(len(reader.complete_marker_rail(noise)),24)

    def test_background_square_does_not_replace_top_form_marker(self):
        image = np.full((1333,1000),255,dtype=np.uint8)
        for x,y in [*reader.REFERENCE, (960,30), (30,1110), (200,1300), (975,1310)]:
            cv2.rectangle(image,(round(x-20),round(y-20)),(round(x+20),round(y+20)),0,-1)
        aligned=align_markers(image)
        self.assertLess(int(aligned[76,877]),30)
        self.assertLess(int(aligned[1160,892]),30)

    def test_basic_mark_patterns(self):
        self.assertEqual(classify([.05, .1, .4, .1, .1]), "3")
        self.assertEqual(classify([0, .01, .02, .03, .04]), "blank")
        self.assertEqual(classify([.43, .42, .1, .09, .08]), "multiple")

    def test_missing_registration_does_not_produce_guesses(self):
        empty = np.full((1333, 1000), 255, dtype=np.uint8)
        with self.assertRaises(ValueError):
            align_markers(empty)
        with self.assertRaises(ValueError):
            locate_grid(empty)
        with patch.object(reader, 'registration_reference', return_value=(empty, [], [], np.ones((2,128),np.float32), empty)):
            with self.assertRaises(ValueError):
                reader.register_form(empty)

    def test_sloped_marker_rails_are_registered(self):
        image = np.full((1333, 1000), 255, dtype=np.uint8)
        left = np.array([(240-100*i/24,450+28*i) for i in range(25)])
        right = np.array([(900,320+30*i) for i in range(25)])
        for x,y in np.concatenate((left,right)):
            cv2.rectangle(image,(round(x-10),round(y-3)),(round(x+10),round(y+3)),0,-1)
        for row,start,step,offset in [(0,280,165,-45),(-1,200,175,70)]:
            for column in range(4):
                for option in range(5):
                    x=start+step*column+20*option
                    fraction=(x-left[row,0])/(right[row,0]-left[row,0])
                    y=left[row,1]+fraction*(right[row,1]-left[row,1])+offset
                    cv2.rectangle(image,(round(x-2),round(y-10)),(round(x+2),round(y+10)),0,-1)
        centers=locate_grid(image)
        self.assertEqual(len(centers),100)
        self.assertTrue(all(len(row)==5 and row[0][0]<row[-1][0] for row in centers))

    def test_appending_batch_preserves_frozen_predictions(self):
        scratch=Path(__file__).resolve().parents[1]/"presentation_build"
        scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as folder:
            root=Path(folder);meta=root/"meta";meta.mkdir()
            inventory=meta/"image_inventory_verified.csv"
            with inventory.open('w',newline='',encoding='utf-8-sig') as f:
                writer=csv.DictWriter(f,fieldnames=['sheet_id','capture_role','pair_status','image_id'])
                writer.writeheader()
                writer.writerows({'sheet_id':sheet,'capture_role':role,'pair_status':'verified','image_id':sheet+role} for sheet in ['S0001','S0002'] for role in ['A','B'])
            output=meta/'answer_pilot_proposals.json'
            frozen={'A':{'image_id':'S0001A','rows':[],'error':'frozen'},'B':{'image_id':'S0001B','rows':[{'question_no':1,'proposed':'5'}],'error':''}}
            output.write_text(json.dumps({'version':1,'method':'frozen-v1','run_id':'original-run','sheets':{'S0001':frozen},'sheet_ids':['S0001']}),encoding='utf-8')
            def fake_read(row,sheet,role):return {'image_id':row['image_id'],'rows':[],'error':'fixture'}
            with patch.multiple(reader,ROOT=root,META=meta,ASSETS=meta/'assets',OUTPUT=output),patch.object(reader,'read_form',side_effect=fake_read),patch.object(sys,'argv',['build_answer_pilot.py','--start','S0002','--end','S0002']):
                reader.main()
                updated=json.loads(output.read_text(encoding='utf-8'))
                self.assertEqual(updated['sheets']['S0001'],frozen)
                self.assertEqual(updated['batches'][0]['run_id'],'original-run')
                self.assertEqual(updated['batches'][1]['sheet_ids'],['S0002'])
                before=output.read_bytes()
                with self.assertRaises(SystemExit):reader.main()
                self.assertEqual(output.read_bytes(),before)
                (meta/'pairing_review_holds.csv').write_text('sheet_id,review_status\nS0002,pending\n',encoding='utf-8')
                with self.assertRaisesRegex(SystemExit, 'pairing holds'):
                    reader.main()
                self.assertEqual(output.read_bytes(),before)


if __name__ == "__main__":
    unittest.main()
