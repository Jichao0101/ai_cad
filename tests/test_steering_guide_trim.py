"""非法比例在访问CAD对象前拒绝，避免生成错误裁剪分支。"""
import unittest
from projects.steering_wheel import native_guide


class GuideTrimTests(unittest.TestCase):
    def test_ambiguous_section_and_invalid_dimensions_rejected(self):
        rectangle={'width_mm':12,'thickness_mm':8.4,'thickness_direction':[0,0,1]}
        with self.assertRaisesRegex(ValueError,'exclusively'):native_guide.create(None,None,2,rectangle=rectangle)
        with self.assertRaisesRegex(ValueError,'exclusively'):native_guide.create(None,None)
        for value in [0,-1,True,float('nan')]:
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'dimensions'):
                native_guide.create(None,None,rectangle={**rectangle,'thickness_mm':value})

    def test_invalid_intervals_rejected_before_cad_access(self):
        for start,end in [(-.1,.8),(.2,1.1),(.5,.5),(.8,.2),(True,.8),(0,float('nan')),(0,'0.8')]:
            with self.subTest(start=start,end=end),self.assertRaisesRegex(ValueError,'Guide interval'):
                native_guide.create(None,None,2,start,end)


if __name__=='__main__':unittest.main()
