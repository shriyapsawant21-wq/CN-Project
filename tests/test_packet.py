import unittest

from packet import PacketError, decode_packet, encode_packet


class PacketTests(unittest.TestCase):
    def test_round_trip_preserves_header_and_payload(self):
        header = {"type": "data", "seq": 42, "block_id": 4}
        payload = b"network-payload"

        decoded_header, decoded_payload = decode_packet(encode_packet(header, payload))

        self.assertEqual(decoded_header, header)
        self.assertEqual(decoded_payload, payload)

    def test_rejects_a_truncated_datagram(self):
        with self.assertRaises(PacketError):
            decode_packet(b"\x00\x00")


if __name__ == "__main__":
    unittest.main()
