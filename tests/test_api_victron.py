import unittest
from unittest.mock import Mock

from api_victron import VictronMonitor


class VictronMonitorFormattingTests(unittest.TestCase):
    def setUp(self):
        self.monitor = VictronMonitor()

    def test_voltage_is_unavailable_until_a_valid_read(self):
        self.assertIsNone(self.monitor.get_voltage())
        self.monitor.parse_ve_direct_frame("V\t13200")
        self.assertEqual(self.monitor.get_voltage(), 13.2)

    def test_malformed_voltage_is_unavailable(self):
        self.monitor.parse_ve_direct_frame("V\tnot-a-number")
        self.assertIsNone(self.monitor.get_voltage())

    def test_hex_capacity_frames_use_little_endian_decimal_ah(self):
        self.assertEqual(VictronMonitor._build_hex_frame(0x7, 0xED00), ":700ED0061\n")
        self.assertEqual(VictronMonitor._build_hex_frame(0x8, 0xED00, 200), ":800ED00C80098\n")

    def test_read_battery_capacity_converts_hex_payload_to_decimal_ah(self):
        self.monitor.serial_conn = Mock()
        self.monitor.serial_conn.readline.return_value = b":700ED00C80099\r\n"

        capacity = self.monitor.read_battery_capacity()

        self.assertEqual(capacity, 200)
        self.monitor.serial_conn.write.assert_called_once_with(b":700ED0061\n")

    def test_write_battery_capacity_sends_decimal_ah_as_hex(self):
        self.monitor.serial_conn = Mock()

        self.monitor.write_battery_capacity(200)

        self.monitor.serial_conn.write.assert_called_once_with(b":800ED00C80098\n")

    def test_write_battery_capacity_rejects_invalid_values(self):
        self.monitor.serial_conn = Mock()
        for capacity in (0, 200.5, True):
            with self.subTest(capacity=capacity), self.assertRaises(ValueError):
                self.monitor.write_battery_capacity(capacity)
        self.monitor.serial_conn.write.assert_not_called()

    def test_format_ttg_handles_zero(self):
        self.assertEqual(self.monitor.format_ttg(0), "N/A")

    def test_format_ttg_handles_under_one_hour(self):
        self.assertEqual(self.monitor.format_ttg(59), "59m")

    def test_format_ttg_handles_exact_hour(self):
        self.assertEqual(self.monitor.format_ttg(60), "1h 0m")

    def test_format_ttg_handles_hour_and_minutes(self):
        self.assertEqual(self.monitor.format_ttg(61), "1h 1m")

    def test_format_current_handles_charging(self):
        self.assertEqual(self.monitor.format_current(5.2), "5.20A ↑")

    def test_format_current_handles_discharging(self):
        self.assertEqual(self.monitor.format_current(-3.1), "3.10A ↓")

    def test_format_current_handles_idle(self):
        self.assertEqual(self.monitor.format_current(0), "0.00A")


if __name__ == "__main__":
    unittest.main()
