import unittest
import numpy as np
import cv2
from app import find_hearts, confirmed, progress_position, C, INPUT

class DetectionTest(unittest.TestCase):
    def setUp(self):
        self.page=np.full((780,416,3),255,np.uint8)
        self.icon=np.full((16,18,3),255,np.uint8)
        points=np.array([[9,14],[2,7],[2,4],[4,2],[7,2],[9,4],[11,2],[14,2],[16,4],[16,7]],np.int32)
        cv2.polylines(self.icon,[points],True,(180,180,180),1,cv2.LINE_AA)
        self.template=cv2.cvtColor(self.icon,cv2.COLOR_RGB2GRAY)

    def test_match_and_nonmax(self):
        self.page[300:316,355:373]=self.icon
        self.page[540:556,355:373]=self.icon
        hits=find_hearts(self.page,self.template,416)
        self.assertEqual(len(hits),2)
        self.assertEqual([h[2] for h in hits],[300,540])

    def test_exclude_liked_navigation_and_wrong_column(self):
        self.page[300:316,355:373]=self.icon
        self.page[300:316,355:373][np.min(self.icon,axis=2)<240]=(215,85,56)
        self.page[730:746,355:373]=self.icon
        self.page[450:466,100:118]=self.icon
        self.assertEqual(find_hearts(self.page,self.template,416),[])

    def test_verify_requires_new_color(self):
        colored=self.icon.copy();colored[5:11,5:13]=(211,90,65)
        self.assertTrue(confirmed(self.icon,colored))
        self.assertFalse(confirmed(self.icon,self.icon))
        self.assertFalse(confirmed(colored,colored))

    def test_input_abi(self):
        self.assertEqual(C.sizeof(INPUT),40 if C.sizeof(C.c_void_p)==8 else 28)

    def test_progress_avoids_target(self):
        for target in [(0,40,416,820),(1500,40,1916,820),(500,330,916,1000),(-1800,30,-1384,810)]:
            work=(-1920,0,0,1080) if target[0]<0 else (0,0,1920,1080)
            x,y=progress_position(target,work,356,354)
            self.assertTrue(work[0]<=x and x+356<=work[2] and work[1]<=y and y+354<=work[3])
            self.assertTrue(x>=target[2] or x+356<=target[0] or y>=target[3] or y+354<=target[1])

    def test_progress_rejects_no_space(self):
        with self.assertRaises(RuntimeError):progress_position((0,0,1920,1080),(0,0,1920,1080),356,354)

if __name__=='__main__': unittest.main()
