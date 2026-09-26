import unittest

from api_victron import VictronMonitor


class VictronMonitorFormattingTests(unittest.TestCase):
    def setUp(self):
        self.monitor = VictronMonitor()

    def test_format_ttg_handles_zero(self):
        self.assertEqual(self.monitor.format_ttg(0), "N/A")

    def test_format_ttg_handles_under_one_hour(self):
        self.assertEqual(self.monitor.format_ttg(59), "59m")

    def test_format_ttg_handles_exact_hour(self):
        self.assertEqual(self.monitor.format_ttg(60), "1h 0m")

    def test_format_ttg_handles_hour_and_minutes(self):
        self.assertEqual(self.monitor.format_ttg(61), "1h 1m")

    def test_format_current_handles_charging(self):
        self.assertEqual(self.monitor.format_current(5.2), "5.2A ↑")

    def test_format_current_handles_discharging(self):
        self.assertEqual(self.monitor.format_current(-3.1), "3.1A ↓")

    def test_format_current_handles_idle(self):
        self.assertEqual(self.monitor.format_current(0), "0.0A")


if __name__ == "__main__":
    unittest.main()
