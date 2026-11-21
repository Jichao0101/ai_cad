import math,unittest
from projects.steering_wheel import symmetry_points


class SymmetryTests(unittest.TestCase):
    def test_translated_rotated_plane_and_reversed_pair_order(self):
        q=math.sqrt(.5);normal=[q,q,0];center=[10,20,30]
        other=[center[0]+5*q,center[1]-5*q,40]
        pairs=[[[c-r*n for c,n in zip(p,normal)],[c+r*n for c,n in zip(p,normal)]] for p,r in [(center,10),(other,20)]]
        pairs[1].reverse()
        result=symmetry_points.solve(pairs,normal)
        for actual,expected in zip(result['normal'],normal):self.assertAlmostEqual(actual,expected)
        self.assertLess(result['maximum_pair_deviation_mm'],1e-10)
        opposite=symmetry_points.solve(pairs,[-v for v in normal])
        self.assertLess(sum((a+b)**2 for a,b in zip(opposite['normal'],normal)),1e-20)

    def test_bad_pairing_and_nonparallel_pairs_rejected(self):
        cases=[[[[0,-1,0],[0,1,0]],[[1,-1,0],[2,1,0]]],
               [[[0,-1,0],[0,1,0]],[[1,0,0],[1,2,0]]]]
        for pairs in cases:
            with self.subTest(pairs=pairs),self.assertRaisesRegex(ValueError,'common symmetry plane'):
                symmetry_points.solve(pairs,[0,1,0])

    def test_degenerate_or_ambiguous_inputs_rejected(self):
        cases=[([[[0,0,0],[0,0,0]],[[1,-1,0],[1,1,0]]],[0,1,0]),
               ([[[0,-1,0],[0,1,0]],[[0,-2,0],[0,2,0]]],[0,1,0]),
               ([[[0,-1,0],[0,1,0]],[[1,-2,0],[1,2,0]]],[1,0,0])]
        for pairs,normal in cases:
            with self.subTest(pairs=pairs),self.assertRaises(ValueError):symmetry_points.solve(pairs,normal)


if __name__=='__main__':unittest.main()
