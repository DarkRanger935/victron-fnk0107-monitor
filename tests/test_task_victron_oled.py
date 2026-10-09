import unittest
import types
import sys
import os
import socket
import tempfile
import threading
import time
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
from task_manager import TaskManager


class VictronOLEDTaskHelperTests(unittest.TestCase):
    def make_task(self):
        return VictronOLEDTask.__new__(VictronOLEDTask)

    def test_normalize_usage_values_handles_scalars_and_sequences(self):
        task = self.make_task()
        self.assertEqual(task.normalize_usage_values([45, 1.2, 2.0], 78), (45, 78))

    def test_normalize_usage_values_handles_empty_sequences(self):
        task = self.make_task()
        self.assertEqual(task.normalize_usage_values([], ()), (0, 0))

    def test_configured_alert_colors_use_defaults_and_preserve_zero_channels(self):
        task = self.make_task()
        task.config_manager = Mock()
        task.config_manager.get_section.return_value = {
            "alternating_colour_1": {"red_value": 0, "green_value": 10},
            "alternating_colour_2": {"blue_value": 0},
        }

        colors = task.get_configured_led_colors(
            "LED Victron Voltage Alert Colours",
            ((255, 0, 0), (0, 0, 255)),
        )

        self.assertEqual(colors, ((0, 10, 0), (0, 0, 0)))

    def test_atak_payload_activates_and_clears_emergency_state(self):
        task = self.make_task()
        task.atak_alert_lock = threading.Lock()
        task.atak_alerts = {}
        task.atak_alert_active = False
        task.atak_alert_text = ""
        task.atak_scroll_index = 0

        self.assertTrue(task.handle_atak_payload("false|MEDICAL|Unit 7|12S UD 12345 67890\n"))
        self.assertTrue(task.handle_atak_payload("false|CASEVAC|Unit 8|12S UD 11111 22222"))
        self.assertEqual(
            task.get_atak_alert_state(),
            (True, "CASEVAC | Unit 8 | 12S UD 11111 22222"),
        )

        self.assertTrue(task.handle_atak_payload("true|MEDICAL CLEARED|Unit 7|12S UD 12345 67890"))
        self.assertEqual(
            task.get_atak_alert_state(),
            (True, "CASEVAC | Unit 8 | 12S UD 11111 22222"),
        )

        self.assertTrue(task.handle_atak_payload("true|CASEVAC CLEARED|Unit 8|12S UD 11111 22222"))
        self.assertEqual(task.get_atak_alert_state(), (False, ""))
        self.assertFalse(task.handle_atak_payload("invalid|MEDICAL|Unit 7|coordinates"))

    def test_atak_socket_server_receives_payload_and_cleans_up(self):
        task = self.make_task()
        task.atak_alert_lock = threading.Lock()
        task.atak_alerts = {}
        task.atak_alert_active = False
        task.atak_alert_text = ""
        task.atak_scroll_index = 0
        task.alert_socket_path = os.path.join(tempfile.gettempdir(), f"victron-alerts-{os.getpid()}.sock")
        task.alert_server = None
        task.alert_server_thread = None
        task.alert_server_stop = threading.Event()
        task.alert_socket_bound = False

        try:
            task.start_alert_server()
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.connect(task.alert_socket_path)
            client.sendall(b"false|CASEVAC|Unit 8|12S UD 11111 22222\n")
            client.close()

            deadline = time.time() + 1
            while not task.get_atak_alert_state()[0] and time.time() < deadline:
                time.sleep(0.01)

            self.assertEqual(
                task.get_atak_alert_state(),
                (True, "CASEVAC | Unit 8 | 12S UD 11111 22222"),
            )
        finally:
            task.stop_alert_server()

        self.assertFalse(os.path.exists(task.alert_socket_path))

    def test_atak_marquee_and_led_override_restore_normal_mode(self):
        task = self.make_task()
        task.oled = Mock()
        task.atak_scroll_index = 0

        task.render_atak_alert("MEDICAL | Unit 7 | MGRS")

        self.assertEqual(task.oled.draw_text.call_args_list[0].args[0], "ATAK EMERGENCY")
        self.assertEqual(task.oled.draw_text.call_args_list[1].args[0], "   MEDICAL | Uni")
        task.oled.show.assert_called_once_with()

        task.expansion = Mock()
        task.last_led_mode = None
        task.last_led_color = None
        task.static_led_mode = 1
        task.normal_led_mode = 2
        task.atak_led_active = False
        task.atak_led_toggle = False
        task.atak_last_toggle = None
        task.alert_state = False
        task.follow_led_color_primed = True
        task.last_follow_led_color = (0, 6, 6)
        task.normal_led_color = (0, 6, 6)
        task.atak_alert_colors = ((255, 0, 0), (0, 255, 0))

        with patch("task_victron_oled.time.time", side_effect=(10, 10.31)):
            task.update_atak_led_state(True)
            task.update_atak_led_state(True)
            task.update_atak_led_state(False)

        self.assertEqual(
            task.expansion.set_all_led_color.call_args_list,
            [
                unittest.mock.call(255, 0, 0),
                unittest.mock.call(0, 255, 0),
                unittest.mock.call(0, 6, 6),
            ],
        )
        self.assertIn(unittest.mock.call(2), task.expansion.set_led_mode.call_args_list[1:])

    def test_format_power_header_and_direction_use_two_decimals(self):
        task = self.make_task()
        self.assertEqual(task.format_power_header(13.2, 3.3), "43.56W")
        self.assertEqual(task.format_power_header(13.2, -3.3), "43.56W")
        self.assertEqual(task.format_power_header(13.2, 0), "0.00W")
        self.assertEqual(task.get_charge_direction(3.3), "↑")
        self.assertEqual(task.get_charge_direction(-3.3), "↓")
        self.assertEqual(task.get_charge_direction(0), "→")

    def test_screen_durations_match_each_screen_category(self):
        task = self.make_task()
        task.screen_durations = task.get_configured_screen_durations({})

        screen_names = ("date_time", "utilization", "fans", "temperatures", "victron")
        self.assertEqual([task.get_screen_duration(name) for name in screen_names], [7, 15, 7, 7, 30])

    def test_screen_duration_legacy_config_remains_a_fallback(self):
        durations = VictronOLEDTask.get_configured_screen_durations({
            "system_screen_display_time": 9,
            "screen2": {"display_time": 31},
        })

        self.assertEqual(durations, {
            "date_time": 9,
            "utilization": 9,
            "fans": 9,
            "temperatures": 9,
            "victron": 31,
        })

    def test_missing_or_invalid_voltage_does_not_trigger_alert(self):
        task = self.make_task()
        task.low_voltage_threshold = 12.8
        task.critical_voltage_threshold = 12.7

        for voltage in (None, "invalid", float("nan"), float("inf")):
            with self.subTest(voltage=voltage):
                self.assertEqual(task.check_voltage_alert(voltage), (False, False))

    def test_fan_speeds_use_cpu_pwm_and_two_case_pwm_channels(self):
        task = self.make_task()
        task.system_info = Mock()
        task.system_info.get_raspberry_pi_fan_duty.return_value = 64
        task.expansion = Mock()
        task.expansion.get_fan_duty.return_value = [128, 192, 255]

        fan_speeds = task.get_fan_speeds()

        self.assertAlmostEqual(fan_speeds[0], 64 / 255 * 100)
        self.assertAlmostEqual(fan_speeds[1], 128 / 255 * 100)
        self.assertAlmostEqual(fan_speeds[2], 192 / 255 * 100)
        task.system_info.get_raspberry_pi_fan_duty.assert_called_once_with()
        task.expansion.get_fan_duty.assert_called_once_with()

    def test_fan_screen_labels_cpu_and_case_channels(self):
        task = self.make_task()
        task.oled = Mock()

        task.oled_ui_fan_speeds([25, 50, 75])

        labels = [call.args[0] for call in task.oled.draw_text.call_args_list]
        self.assertEqual(labels, ["CPU", "25%", "F1", "50%", "F2", "75%"])

    def test_task_manager_reads_missing_capacity_then_writes_it_once(self):
        manager = TaskManager.__new__(TaskManager)
        manager.config_manager = Mock()
        manager.config_manager.get_section.return_value = {"port": "/dev/victron"}
        monitor = Mock()
        monitor.connect.return_value = True
        monitor.read_battery_capacity.return_value = 300
        monitor.serial_conn = Mock(is_open=True)

        with patch("task_manager.api_victron.VictronMonitor", return_value=monitor):
            manager.sync_battery_capacity()

        monitor.read_battery_capacity.assert_called_once_with()
        manager.config_manager.set_value.assert_called_once_with("Victron", "battery_capacity_ah", 300)
        manager.config_manager.save_config.assert_called_once_with()
        monitor.write_battery_capacity.assert_called_once_with(300)
        monitor.serial_conn.close.assert_called_once_with()

    def test_task_manager_writes_configured_capacity_without_reading(self):
        manager = TaskManager.__new__(TaskManager)
        manager.config_manager = Mock()
        manager.config_manager.get_section.return_value = {"battery_capacity_ah": 450}
        monitor = Mock()
        monitor.connect.return_value = True
        monitor.serial_conn = Mock(is_open=True)

        with patch("task_manager.api_victron.VictronMonitor", return_value=monitor):
            manager.sync_battery_capacity()

        monitor.read_battery_capacity.assert_not_called()
        monitor.write_battery_capacity.assert_called_once_with(450)
        manager.config_manager.set_value.assert_not_called()
        manager.config_manager.save_config.assert_not_called()

    def test_task_manager_syncs_capacity_once_during_startup(self):
        with (
            patch("task_manager.ConfigManager"),
            patch("task_manager.Expansion"),
            patch("task_manager.atexit.register"),
            patch("task_manager.signal.signal"),
            patch.object(TaskManager, "sync_battery_capacity") as sync_capacity,
        ):
            TaskManager()

        sync_capacity.assert_called_once_with()

    def test_critical_numeric_voltage_triggers_shutdown(self):
        task = self.make_task()
        task.low_voltage_threshold = 12.8
        task.critical_voltage_threshold = 12.7
        self.assertEqual(task.check_voltage_alert(12.6), (True, True))

    def test_victron_screen_shows_shunt_error_for_missing_voltage(self):
        task = self.make_task()
        task.oled = Mock()
        task.oled_ui_victron_stats("Shunt Err", None, "0.00A", 0, "N/A")

        self.assertIn(
            unittest.mock.call("Shunt Err", position=((0, 0), (64, 20)), directory="left", offset=(2, 0), font_size=12),
            task.oled.draw_text.call_args_list,
        )
        self.assertIn(
            unittest.mock.call("Shunt Err", position=((0, 22), (64, 42)), directory="left", offset=(2, 0), font_size=12),
            task.oled.draw_text.call_args_list,
        )

    def test_victron_screen_groups_two_decimal_readouts_by_row(self):
        task = self.make_task()
        task.oled = Mock()

        task.oled_ui_victron_stats("43.56W", 13.2, "3.30A ↑", 87, "4h 32m", "↑")

        calls = task.oled.draw_text.call_args_list
        self.assertEqual([call.args[0] for call in calls], ["43.56W", "↑", "3.30A", "13.20V", "87.00%", "Rem 4h 32m"])
        self.assertEqual(calls[0].kwargs["position"], ((0, 0), (64, 20)))
        self.assertEqual(calls[1].kwargs["position"], ((56, 0), (74, 20)))
        self.assertEqual(calls[2].kwargs["position"], ((74, 0), (128, 20)))
        self.assertEqual(calls[3].kwargs["position"], ((0, 22), (64, 42)))
        self.assertEqual(calls[4].kwargs["position"], ((64, 22), (128, 42)))
        self.assertEqual(calls[5].kwargs["font_size"], 14)

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
