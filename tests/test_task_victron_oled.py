import unittest
import types
import sys
from unittest.mock import Mock, patch

api_expansion_stub = types.ModuleType("api_expansion")
api_expansion_stub.Expansion = object
sys.modules.setdefault("api_expansion", api_expansion_stub)

api_oled_stub = types.ModuleType("api_oled")
api_oled_stub.OLED = object
sys.modules.setdefault("api_oled", api_oled_stub)

api_system_stub = types.ModuleType("api_systemInfo")
api_system_stub.SystemInformation = object
sys.modules.setdefault("api_systemInfo", api_system_stub)

api_json_stub = types.ModuleType("api_json")
api_json_stub.ConfigManager = object
sys.modules.setdefault("api_json", api_json_stub)

from task_victron_oled import VictronOLEDTask


class VictronOLEDTaskHelperTests(unittest.TestCase):
    def make_task(self):
        return VictronOLEDTask.__new__(VictronOLEDTask)

    def test_normalize_usage_values_handles_scalars_and_sequences(self):
        task = self.make_task()
        self.assertEqual(task.normalize_usage_values([45, 1.2, 2.0], 78), (45, 78))

    def test_normalize_usage_values_handles_empty_sequences(self):
        task = self.make_task()
        self.assertEqual(task.normalize_usage_values([], ()), (0, 0))

    def test_format_power_header_uses_current_sign(self):
        task = self.make_task()
        self.assertEqual(task.format_power_header(13.2, 3.3), "44W ↑")
        self.assertEqual(task.format_power_header(13.2, -3.3), "44W ↓")
        self.assertEqual(task.format_power_header(13.2, 0), "0.0W →")

    def test_missing_or_invalid_voltage_does_not_trigger_alert(self):
        task = self.make_task()
        task.low_voltage_threshold = 12.8
        task.critical_voltage_threshold = 12.7

        for voltage in (None, "invalid", float("nan"), float("inf")):
            with self.subTest(voltage=voltage):
                self.assertEqual(task.check_voltage_alert(voltage), (False, False))

    def test_critical_numeric_voltage_triggers_shutdown(self):
        task = self.make_task()
        task.low_voltage_threshold = 12.8
        task.critical_voltage_threshold = 12.7
        self.assertEqual(task.check_voltage_alert(12.6), (True, True))

    def test_victron_screen_shows_shunt_error_for_missing_voltage(self):
        task = self.make_task()
        task.oled = Mock()
        task.oled_ui_victron_stats("Shunt Err", None, "0.0A", 0, "N/A")

        self.assertIn(
            unittest.mock.call("Shunt Err", position=((0, 13), (128, 25)), directory="left", offset=(4, 0), font_size=12),
            task.oled.draw_text.call_args_list,
        )

    def test_graceful_shutdown_counts_down_before_poweroff(self):
        task = self.make_task()
        task.oled = Mock(width=128, height=64)
        task.expansion = Mock()

        with patch("task_victron_oled.time.sleep") as sleep, patch("task_victron_oled.os.system") as system:
            task.graceful_shutdown()

        self.assertEqual(sleep.call_count, 30)
        self.assertIn(
            unittest.mock.call("Shutdown in 30s", position=((0, 42), (128, 56)), directory="center", offset=(0, 0), font_size=11),
            task.oled.draw_text.call_args_list,
        )
        self.assertIn(
            unittest.mock.call("Shutdown in 1s", position=((0, 42), (128, 56)), directory="center", offset=(0, 0), font_size=11),
            task.oled.draw_text.call_args_list,
        )
        system.assert_called_once_with("sudo shutdown -h now")

    def test_render_screen_routes_utilization_snapshot(self):
        task = self.make_task()
        task.oled_ui_date_time = Mock()
        task.oled_ui_system_stats = Mock()
        task.oled_ui_fan_speeds = Mock()
        task.oled_ui_temperatures = Mock()
        task.oled_ui_victron_stats = Mock()

        snapshot = {
            "date_str": "2026-09-26",
            "time_str": "12:34:56",
            "cpu_usage": 20,
            "memory_percent": 45,
            "disk_percent": 75,
            "cpu_temp": 42,
            "case_temp": 38,
            "fan_speeds": [65, 58, 72],
            "power_text": "44W ↓",
            "voltage": 13.2,
            "current_str": "3.3A ↓",
            "soc": 71,
            "rem_str": "9h 28m",
        }

        task.render_screen("utilization", snapshot)

        task.oled_ui_system_stats.assert_called_once_with(20, 45, 75)
        task.oled_ui_date_time.assert_not_called()
        task.oled_ui_fan_speeds.assert_not_called()
        task.oled_ui_temperatures.assert_not_called()
        task.oled_ui_victron_stats.assert_not_called()


if __name__ == "__main__":
    unittest.main()
