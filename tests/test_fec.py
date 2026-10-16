import unittest

import fec


class FecTests(unittest.TestCase):
    def setUp(self):
        self.data = [bytes([index + 1]) * 64 for index in range(10)]

    def test_recovers_single_erasure(self):
        parity = fec.encode(self.data, 1)
        received = self.data.copy()
        received[4] = None

        recovered = fec.recover(received, {0: parity[0]})

        self.assertEqual(recovered[4], self.data[4])

    def test_recovers_three_erasures_with_four_parity_packets(self):
        parity = fec.encode(self.data, 4)
        received = self.data.copy()
        for index in (1, 5, 8):
            received[index] = None

        recovered = fec.recover(received, {0: parity[0], 1: parity[1], 3: parity[3]})

        for index in (1, 5, 8):
            self.assertEqual(recovered[index], self.data[index])

    def test_recovers_every_loss_pattern_up_to_r(self):
        # Regression: a Vandermonde parity matrix left some 3- and 4-packet loss
        # patterns undecodable even with enough parity.
        import itertools

        for r in (1, 2, 4):
            parity = fec.encode(self.data, r)
            for lost in range(1, r + 1):
                for missing in itertools.combinations(range(10), lost):
                    received = [None if i in missing else p for i, p in enumerate(self.data)]
                    # The receiver uses whichever parity arrived: test the highest-index ones too.
                    for arrived in (range(lost), range(r - lost, r)):
                        recovered = fec.recover(received, {p: parity[p] for p in arrived})
                        self.assertEqual(set(recovered), set(missing))
                        for index in missing:
                            self.assertEqual(recovered[index][: len(self.data[index])], self.data[index])

    def test_returns_empty_result_when_parity_is_insufficient(self):
        parity = fec.encode(self.data, 1)
        received = self.data.copy()
        received[2] = None
        received[7] = None

        self.assertEqual(fec.recover(received, {0: parity[0]}), {})


if __name__ == "__main__":
    unittest.main()
