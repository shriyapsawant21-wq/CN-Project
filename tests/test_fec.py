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

    def test_returns_empty_result_when_parity_is_insufficient(self):
        parity = fec.encode(self.data, 1)
        received = self.data.copy()
        received[2] = None
        received[7] = None

        self.assertEqual(fec.recover(received, {0: parity[0]}), {})


if __name__ == "__main__":
    unittest.main()
