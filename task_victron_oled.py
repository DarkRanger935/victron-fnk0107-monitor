#!/usr/bin/env python3
"""
Victron + FNK0107 OLED Display Monitor Task
Integrates Victron battery monitoring with Freenove case control and OLED display
"""

import sys
import time
import atexit
import signal
import subprocess
import os
import math
import socket
import stat
import threading
from datetime import datetime, timedelta

ATAK_SOCKET_PATH = "/run/victron-monitor/victron_alerts.sock"

try:
    from api_victron import VictronMonitor
    from api_expansion import Expansion
    from api_systemInfo import SystemInformation
    from api_json import ConfigManager
    from api_oled import OLED
except ImportError as e:
    print(f"Import error: {e}")
    sys.exit(1)


class VictronOLEDTask:
    
    def __init__(self):
        self.running = True
        self.config_manager = ConfigManager()
        self.expansion = None
        self.oled = None
        self.system_info = None
        self.victron = None
        self.board_type = None
        self.alert_state = False
        self.alert_color_toggle = False
        self.last_alert_toggle = 0
        self.last_led_mode = None
        self.last_led_color = None
        self.follow_led_color_primed = False
        self.last_follow_led_color = None
        self.static_led_mode = 1
        self.normal_led_mode = 2
        self.font_size = 12
        self.system_screens = ("date_time", "utilization", "fans", "temperatures")
        self.screen_sequence = self.system_screens + ("victron",)
        self.atak_alert_lock = threading.Lock()
        self.atak_alert_active = False
        self.atak_alert_text = ""
        self.atak_scroll_index = 0
        self.atak_led_active = False
        self.atak_led_toggle = False
        self.atak_last_toggle = None
        self.alert_socket_path = ATAK_SOCKET_PATH
        self.alert_server = None
        self.alert_server_thread = None
        self.alert_server_stop = threading.Event()
        self.alert_socket_bound = False
        
        # Load config
        victron_config = self.config_manager.get_value('Victron', 'port') or {}
        oled_config = self.config_manager.get_section('OLED') or {}
        
        self.victron_port = self.config_manager.get_value('Victron', 'port') or '/dev/ttyUSB0'

        default_low_voltage_threshold = 12.8
        default_critical_voltage_threshold = 12.7

        low_voltage_threshold = self.config_manager.get_value('Victron', 'low_voltage_threshold')
        if low_voltage_threshold is None:
            print(f"Warning: 'low_voltage_threshold' not found in config, using default: {default_low_voltage_threshold}V")
            low_voltage_threshold = default_low_voltage_threshold
        self.low_voltage_threshold = low_voltage_threshold

        critical_voltage_threshold = self.config_manager.get_value('Victron', 'critical_voltage_threshold')
        if critical_voltage_threshold is None:
            print(f"Warning: 'critical_voltage_threshold' not found in config, using default: {default_critical_voltage_threshold}V")
            critical_voltage_threshold = default_critical_voltage_threshold
        self.critical_voltage_threshold = critical_voltage_threshold
        self.normal_led_color = (
            self.config_manager.get_value('LED', 'red_value') or 0,
            self.config_manager.get_value('LED', 'green_value') or 6,
            self.config_manager.get_value('LED', 'blue_value') or 6,
        )
        
        self.screen_durations = self.get_configured_screen_durations(oled_config)
        
        try:
            self.expansion = Expansion()
            self.board_type = self.expansion.get_board_type()
            print(f"Expansion board type: {self.board_type}")
        except Exception as e:
            print(f"Error initializing expansion board: {e}")
            sys.exit(1)
        
        try:
            if self.board_type == "FNK0100":
                self.oled = OLED(rotate_angle=0)
            elif self.board_type == "FNK0107":
                self.oled = OLED(rotate_angle=180)
            print("OLED initialized")
        except Exception as e:
            print(f"Error initializing OLED: {e}")
            sys.exit(1)
        
        try:
            self.system_info = SystemInformation()
            print("System information initialized")
        except Exception as e:
            print(f"Error initializing system info: {e}")
            sys.exit(1)
        
        try:
            self.victron = VictronMonitor(port=self.victron_port)
            self.victron.start()
            print(f"Victron monitor started on {self.victron_port}")
            time.sleep(2)  # Wait for initial data
        except Exception as e:
            print(f"Error initializing Victron: {e}")
            sys.exit(1)
        
        self.initialize_normal_led_state()
        
        atexit.register(self.handle_signal)
        signal.signal(signal.SIGTERM, self.handle_signal)
        signal.signal(signal.SIGINT, self.handle_signal)
    
    def handle_signal(self, signum=None, frame=None):
        """Handle shutdown signals"""
        print("\nShutdown signal received")
        self.running = False
        self.stop_alert_server()
        
        try:
            if self.victron:
                self.victron.stop()
        except:
            pass
        
        try:
            if self.oled:
                self.oled.clear()
                self.oled.show()
                self.oled.close()
        except:
            pass
        
        try:
            if self.expansion:
                self.expansion.set_all_led_color(0, 0, 0)
                self.expansion.set_led_mode(0)
        except:
            pass
        
        sys.exit(0)
    
    def check_voltage_alert(self, voltage):
        """
        Check voltage against thresholds and handle alerts
        
        Returns:
            tuple: (alert_active, should_shutdown)
        """
        if not self.is_valid_voltage(voltage):
            return False, False
        voltage = float(voltage)
        if voltage < self.critical_voltage_threshold:
            # Critical shutdown
            return True, True
        elif voltage <= self.low_voltage_threshold:
            # Low voltage alert
            return True, False
        else:
            # Normal
            return False, False

    @staticmethod
    def is_valid_voltage(voltage):
        if isinstance(voltage, bool):
            return False
        try:
            return math.isfinite(float(voltage))
        except (TypeError, ValueError, OverflowError):
            return False
    
    def update_led_state(self, alert_active, override_active=False):
        """
        Update LED color based on alert state
        """
        if override_active:
            self.alert_state = alert_active
            return

        current_time = time.time()
        
        if alert_active:
            entered_alert = False
            if not self.alert_state:
                self.alert_state = True
                self.alert_color_toggle = True
                self.last_alert_toggle = current_time
                entered_alert = True
            
            # Flash red/blue every 1 second
            if not entered_alert and current_time - self.last_alert_toggle >= 1.0:
                self.alert_color_toggle = not self.alert_color_toggle
                self.last_alert_toggle = current_time
            
            if self.alert_color_toggle:
                self._set_led_state(1, (255, 0, 0))  # Red
            else:
                self._set_led_state(1, (0, 0, 255))  # Blue
        else:
            if self.alert_state:
                self.alert_state = False
            self.restore_normal_led_state()
    
    def initialize_normal_led_state(self):
        """Prime the board with the configured follow color, then hand off to follow mode."""
        force_priming = not self.follow_led_color_primed
        self._ensure_led_mode(self.static_led_mode)
        if force_priming or self.last_follow_led_color != self.normal_led_color:
            self.expansion.set_all_led_color(*self.normal_led_color)
            self.last_led_color = self.normal_led_color
        self._ensure_led_mode(self.normal_led_mode)
        self.follow_led_color_primed = True
        self.last_follow_led_color = self.normal_led_color
    
    def restore_normal_led_state(self):
        """Restore follow mode without replaying the full-strip color flash."""
        if not self.follow_led_color_primed or self.last_follow_led_color != self.normal_led_color:
            self.initialize_normal_led_state()
            return
        self._ensure_led_mode(self.normal_led_mode)
        self.last_follow_led_color = self.normal_led_color
        self.last_led_color = self.last_follow_led_color
    
    def _ensure_led_mode(self, mode):
        """Apply a LED mode only when it changes."""
        if self.last_led_mode != mode:
            self.expansion.set_led_mode(mode)
            self.last_led_mode = mode
    
    def _set_led_state(self, mode, color):
        """Update LED mode/color only when the requested state changes."""
        self._ensure_led_mode(mode)
        
        if self.last_led_color != color:
            self.expansion.set_all_led_color(*color)
            self.last_led_color = color

    def start_alert_server(self):
        """Start the non-blocking Unix-domain socket receiver for ATAK alerts."""
        if self.alert_server_thread and self.alert_server_thread.is_alive():
            return

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        socket_bound = False
        try:
            os.makedirs(os.path.dirname(self.alert_socket_path), exist_ok=True)
            try:
                existing_mode = os.lstat(self.alert_socket_path).st_mode
            except FileNotFoundError:
                pass
            else:
                if not stat.S_ISSOCK(existing_mode):
                    raise OSError(f"Refusing to replace non-socket path: {self.alert_socket_path}")
                os.unlink(self.alert_socket_path)

            server.bind(self.alert_socket_path)
            socket_bound = True
            os.chmod(self.alert_socket_path, 0o660)
            server.listen(5)
            server.settimeout(0.5)
            self.alert_server_stop.clear()
            self.alert_server = server
            self.alert_socket_bound = True
            self.alert_server_thread = threading.Thread(
                target=self._listen_for_atak_alerts,
                daemon=True,
            )
            self.alert_server_thread.start()
            print(f"[ATAK] Listening for alerts on {self.alert_socket_path}")
        except OSError as error:
            server.close()
            if socket_bound and os.path.exists(self.alert_socket_path):
                try:
                    if stat.S_ISSOCK(os.lstat(self.alert_socket_path).st_mode):
                        os.unlink(self.alert_socket_path)
                except OSError:
                    pass
            self.alert_server = None
            self.alert_socket_bound = False
            print(f"[ATAK] Unable to start alert socket: {error}")

    def _listen_for_atak_alerts(self):
        server = self.alert_server
        while not self.alert_server_stop.is_set():
            try:
                connection, _ = server.accept()
            except socket.timeout:
                continue
            except OSError:
                if not self.alert_server_stop.is_set():
                    print("[ATAK] Alert socket stopped unexpectedly")
                return

            with connection:
                connection.settimeout(1)
                payload = bytearray()
                try:
                    while len(payload) < 4096:
                        chunk = connection.recv(min(1024, 4096 - len(payload)))
                        if not chunk:
                            break
                        payload.extend(chunk)
                        if b"\n" in chunk:
                            break
                except (OSError, socket.timeout):
                    continue

            if payload:
                self.handle_atak_payload(payload.decode("utf-8", errors="replace").strip())

    def handle_atak_payload(self, payload):
        """Apply a STATUS|TYPE|CALLSIGN|MGRS message from the ATAK service."""
        parts = payload.split("|", 3)
        if len(parts) != 4 or parts[0].strip().lower() not in ("true", "false"):
            return False

        is_cleared = parts[0].strip().lower() == "true"
        alert_type, callsign, mgrs_position = (
            value.strip().replace("\r", " ").replace("\n", " ")
            for value in parts[1:]
        )

        with self.atak_alert_lock:
            if is_cleared:
                self.atak_alert_active = False
                self.atak_alert_text = ""
                self.atak_scroll_index = 0
            else:
                self.atak_alert_active = True
                self.atak_alert_text = (
                    f"{alert_type or 'EMERGENCY ALERT'} | "
                    f"{callsign or 'UNKNOWN'} | {mgrs_position or 'UNKNOWN COORD'}"
                )[:512]
                self.atak_scroll_index = 0

        print("[ATAK] Emergency alert cleared" if is_cleared else "[ATAK] Emergency alert received")
        return True

    def get_atak_alert_state(self):
        with self.atak_alert_lock:
            return self.atak_alert_active, self.atak_alert_text

    def stop_alert_server(self):
        self.alert_server_stop.set()
        server = self.alert_server
        self.alert_server = None
        if server:
            server.close()

        thread = self.alert_server_thread
        self.alert_server_thread = None
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1)

        if self.alert_socket_bound:
            try:
                if stat.S_ISSOCK(os.lstat(self.alert_socket_path).st_mode):
                    os.unlink(self.alert_socket_path)
            except (FileNotFoundError, OSError):
                pass
            self.alert_socket_bound = False

    def update_atak_led_state(self, alert_active):
        """Flash the case LEDs during ATAK emergencies and restore normal mode on clear."""
        if not alert_active:
            if self.atak_led_active:
                self.atak_led_active = False
                self.atak_last_toggle = None
                if not self.alert_state:
                    self.restore_normal_led_state()
            return

        current_time = time.time()
        if not self.atak_led_active:
            self.atak_led_active = True
            self.atak_led_toggle = True
            self.atak_last_toggle = current_time
        elif current_time - self.atak_last_toggle >= 0.3:
            self.atak_led_toggle = not self.atak_led_toggle
            self.atak_last_toggle = current_time

        color = (255, 0, 0) if self.atak_led_toggle else (0, 255, 0)
        self._set_led_state(self.static_led_mode, color)

    def render_atak_alert(self, alert_text):
        """Render one scrolling ATAK emergency frame without blocking the monitor loop."""
        scrolling_text = f"   {alert_text}   "
        start = self.atak_scroll_index % len(scrolling_text)
        repeated_text = scrolling_text * 2
        visible_text = repeated_text[start:start + 16]

        self.oled.clear()
        self.oled.draw_text(
            "ATAK EMERGENCY",
            position=((0, 7), (128, 24)),
            directory="center",
            offset=(0, 0),
            font_size=13,
        )
        self.oled.draw_text(
            visible_text,
            position=((0, 27), (128, 48)),
            directory="left",
            offset=(0, 0),
            font_size=14,
        )
        self.oled.draw_line(((0, 51), (128, 51)), fill="white")
        self.oled.show()
        self.atak_scroll_index = (start + 1) % len(scrolling_text)
    
    def format_power_header(self, voltage, current):
        """Format power for the Victron screen."""
        watts = abs(voltage * current)
        return f"{watts:.2f}W"

    @staticmethod
    def get_charge_direction(current):
        if current > 0:
            return '↑'
        elif current < 0:
            return '↓'
        return '→'
    
    def get_screen_duration(self, screen_name):
        """Return the configured duration for a given screen."""
        return self.screen_durations.get(screen_name, 7.0)

    @staticmethod
    def get_configured_screen_durations(oled_config):
        """Resolve per-screen durations with support for legacy timing settings."""
        defaults = {
            "date_time": 7.0,
            "utilization": 15.0,
            "fans": 7.0,
            "temperatures": 7.0,
            "victron": 30.0,
        }
        configured = oled_config.get("screen_durations") or {}
        legacy_system_duration = oled_config.get("system_screen_display_time")
        screen1_config = oled_config.get("screen1") or {}
        screen2_config = oled_config.get("screen2") or {}
        if legacy_system_duration is None:
            legacy_system_duration = screen1_config.get("display_time")

        durations = {}
        for screen_name, default_duration in defaults.items():
            if configured.get(screen_name) is not None:
                durations[screen_name] = configured[screen_name]
            elif screen_name == "victron":
                durations[screen_name] = screen2_config.get("display_time", default_duration)
            else:
                durations[screen_name] = (
                    legacy_system_duration if legacy_system_duration is not None else default_duration
                )
        return durations
    
    def get_usage_percent(self, usage_data):
        """Normalize usage values to a single numeric percentage."""
        if isinstance(usage_data, (list, tuple)) and usage_data:
            return usage_data[0]
        return usage_data or 0
    
    def normalize_usage_values(self, memory_usage, disk_usage):
        """Normalize memory and disk usage inputs to percentage scalars."""
        return self.get_usage_percent(memory_usage), self.get_usage_percent(disk_usage)

    def get_fan_speeds(self):
        """Return CPU and first two case-fan PWM readings as percentages."""
        case_duty = self.expansion.get_fan_duty()
        if isinstance(case_duty, (list, tuple)):
            case_duties = list(case_duty[:2])
        else:
            case_duties = [case_duty]
        duties = [self.system_info.get_raspberry_pi_fan_duty()] + case_duties
        return [duty / 255.0 * 100 for duty in duties]
    
    def render_screen(self, screen_name, snapshot):
        """Render the active OLED screen from a prepared snapshot."""
        if screen_name == "date_time":
            self.oled_ui_date_time(snapshot["date_str"], snapshot["time_str"])
        elif screen_name == "utilization":
            self.oled_ui_system_stats(snapshot["cpu_usage"], snapshot["memory_percent"], snapshot["disk_percent"])
        elif screen_name == "fans":
            self.oled_ui_fan_speeds(snapshot["fan_speeds"])
        elif screen_name == "temperatures":
            self.oled_ui_temperatures(snapshot["cpu_temp"], snapshot["case_temp"])
        else:
            self.oled_ui_victron_stats(
                snapshot["power_text"],
                snapshot["voltage"],
                snapshot["current_str"],
                snapshot["soc"],
                snapshot["rem_str"],
                snapshot.get("direction_arrow", "→"),
            )
    
    def oled_ui_date_time(self, date_str, time_str):
        """Display the date and time on a dedicated screen."""
        self.oled.clear()
        self.oled.draw_text(time_str, position=((0, 8), (128, 32)), directory="center", offset=(0, 0), font_size=22)
        self.oled.draw_text(date_str, position=((0, 42), (128, 56)), directory="center", offset=(0, 0), font_size=13)
        self.oled.show()
    
    def oled_ui_system_stats(self, cpu_usage, memory_usage, disk_usage):
        """
        Display system hardware utilization with pie charts
        """
        self.oled.clear()
        self.oled.draw_text("CPU", position=((0, 4), (42, 14)), directory="center", offset=(0, 0), font_size=10)
        self.oled.draw_text("MEM", position=((43, 4), (85, 14)), directory="center", offset=(0, 0), font_size=10)
        self.oled.draw_text("DSK", position=((86, 4), (128, 14)), directory="center", offset=(0, 0), font_size=10)
        
        self.oled.draw_circle_with_percentage((21, 30), 14, int(cpu_usage), outline="white", fill="white")
        self.oled.draw_text(f"{int(cpu_usage)}%", position=((0, 48), (42, 60)), directory="center", offset=(0, 0), font_size=11)
        
        self.oled.draw_circle_with_percentage((64, 30), 14, int(memory_usage), outline="white", fill="white")
        self.oled.draw_text(f"{int(memory_usage)}%", position=((43, 48), (85, 60)), directory="center", offset=(0, 0), font_size=11)
        
        self.oled.draw_circle_with_percentage((107, 30), 14, int(disk_usage), outline="white", fill="white")
        self.oled.draw_text(f"{int(disk_usage)}%", position=((86, 48), (128, 60)), directory="center", offset=(0, 0), font_size=11)
        
        self.oled.show()
    
    def oled_ui_fan_speeds(self, fan_speeds):
        """Display fan speeds on their own screen."""
        self.oled.clear()
        extra_fans = max(0, len(fan_speeds) - 3)
        if extra_fans:
            self.oled.draw_text(f"+{extra_fans} more", position=((0, 0), (128, 10)), directory="right", offset=(-2, 0), font_size=9)
        
        if len(fan_speeds) >= 3:
            fan_layout = [
                ("CPU", fan_speeds[0], ((0, 4), (42, 60)), (21, 28)),
                ("F1", fan_speeds[1], ((43, 4), (85, 60)), (64, 28)),
                ("F2", fan_speeds[2], ((86, 4), (128, 60)), (107, 28)),
            ]
        elif len(fan_speeds) >= 2:
            fan_layout = [
                ("CPU", fan_speeds[0], ((0, 4), (64, 60)), (32, 28)),
                ("F1", fan_speeds[1], ((64, 4), (128, 60)), (96, 28)),
            ]
        elif fan_speeds:
            fan_layout = [
                ("CPU", fan_speeds[0], ((0, 4), (128, 60)), (64, 28)),
            ]
        else:
            self.oled.draw_text("No fan data", position=((0, 26), (128, 40)), directory="center", offset=(0, 0), font_size=12)
            self.oled.show()
            return
        
        for label, speed, text_box, center in fan_layout:
            x1, y1 = text_box[0]
            x2, y2 = text_box[1]
            self.oled.draw_text(label, position=((x1, y1), (x2, y1 + 8)), directory="center", offset=(0, 0), font_size=10)
            self.oled.draw_circle_with_percentage(center, 14, int(speed), outline="white", fill="white")
            self.oled.draw_text(f"{int(speed)}%", position=((x1, y2 - 12), (x2, y2)), directory="center", offset=(0, 0), font_size=11)
        
        self.oled.show()
    
    def oled_ui_temperatures(self, cpu_temp, case_temp):
        """Display temperature readings on their own screen."""
        self.oled.clear()
        self.oled.draw_text("CPU", position=((0, 8), (64, 20)), directory="center", offset=(0, 0), font_size=13)
        self.oled.draw_text(f"{int(cpu_temp)}C", position=((0, 28), (64, 48)), directory="center", offset=(0, 0), font_size=18)
        self.oled.draw_line(((64, 8), (64, 56)), fill="white")
        self.oled.draw_text("CASE", position=((64, 8), (128, 20)), directory="center", offset=(0, 0), font_size=13)
        self.oled.draw_text(f"{int(case_temp)}C", position=((64, 28), (128, 48)), directory="center", offset=(0, 0), font_size=18)
        
        self.oled.show()
    
    def oled_ui_victron_stats(self, power_text, voltage, current_str, soc, rem_str, direction_arrow="→"):
        """
        Display Victron battery statistics
        """
        self.oled.clear()
        power_font = 12 if power_text == "Shunt Err" else 14
        self.oled.draw_text(power_text, position=((0, 0), (64, 20)), directory="left", offset=(2, 0), font_size=power_font)
        self.oled.draw_text(direction_arrow, position=((56, 0), (74, 20)), directory="center", offset=(0, 0), font_size=14)
        current_readout = current_str.split()[0] if current_str else "0.00A"
        self.oled.draw_text(current_readout, position=((74, 0), (128, 20)), directory="right", offset=(-2, 0), font_size=14)

        voltage_text = f"{float(voltage):.2f}V" if self.is_valid_voltage(voltage) else "Shunt Err"
        voltage_font = 14 if self.is_valid_voltage(voltage) else 12
        self.oled.draw_text(voltage_text, position=((0, 22), (64, 42)), directory="left", offset=(2, 0), font_size=voltage_font)
        if self.is_valid_voltage(soc):
            soc_text = f"{float(soc):.2f}%"
        else:
            soc_text = str(soc)
        self.oled.draw_text(soc_text, position=((64, 22), (128, 42)), directory="right", offset=(-2, 0), font_size=14)
        self.oled.draw_text(f"Rem {rem_str}", position=((0, 46), (128, 64)), directory="center", offset=(0, 0), font_size=14)
        
        self.oled.show()
    
    def oled_ui_low_voltage_alert(self, voltage):
        """
        Display low voltage alert overlay
        """
        self.oled.clear()
        
        # Draw alert box
        self.oled.draw_rectangle((2, 8, 125, 56), outline="white")
        
        # Alert title
        self.oled.draw_text(u"\u26a0\ufe0f LOW VOLTAGE", position=((4, 10), (124, 20)), directory="center", offset=(0, 0), font_size=11)
        
        # Voltage display
        self.oled.draw_text(f"V: {voltage:.1f}V", position=((4, 22), (124, 32)), directory="center", offset=(0, 0), font_size=12)
        
        # Action required
        self.oled.draw_text("Action Required", position=((4, 34), (124, 42)), directory="center", offset=(0, 0), font_size=10)
        
        # Shutdown imminent (with scrolling if needed)
        shutdown_text = "Shutdown Imminent!"
        self.oled.draw_text(shutdown_text, position=((4, 44), (124, 52)), directory="center", offset=(0, 0), font_size=10)
        
        self.oled.show()
    
    def graceful_shutdown(self, countdown_seconds=30):
        """
        Perform graceful shutdown when voltage drops below critical threshold
        """
        print("\n" + "="*50)
        print("CRITICAL VOLTAGE - INITIATING GRACEFUL SHUTDOWN")
        print("="*50)
        
        # Turn off LED
        self.expansion.set_all_led_color(0, 0, 0)
        self.expansion.set_led_mode(0)
        
        for seconds_remaining in range(countdown_seconds, 0, -1):
            self.oled.clear()
            self.oled.draw_rectangle((0, 0, self.oled.width-1, self.oled.height-1), outline="white")
            self.oled.draw_text("SHUTDOWN", position=((0, 12), (128, 24)), directory="center", offset=(0, 0), font_size=14)
            self.oled.draw_text("Critical Voltage", position=((0, 26), (128, 38)), directory="center", offset=(0, 0), font_size=11)
            self.oled.draw_text(f"Shutdown in {seconds_remaining}s", position=((0, 42), (128, 56)), directory="center", offset=(0, 0), font_size=11)
            self.oled.show()
            time.sleep(1)
        
        # Execute shutdown
        try:
            os.system('sudo shutdown -h now')
        except Exception as e:
            print(f"Shutdown error: {e}")
            sys.exit(1)
    
    def run(self):
        """
        Main event loop
        """
        print("Starting Victron OLED Monitor Task")
        print(f"Low voltage threshold: {self.low_voltage_threshold}V")
        print(f"Critical voltage threshold: {self.critical_voltage_threshold}V")
        
        self.start_alert_server()
        screen_start_time = time.time()
        current_screen_index = 0
        previous_alert_active = False
        previous_atak_alert_active = False
        
        while self.running:
            try:
                # Get Victron data
                voltage = self.victron.get_voltage()
                current = self.victron.get_current()
                soc = self.victron.get_soc()
                ttg = self.victron.get_ttg()
                
                # Check voltage
                alert_active, should_shutdown = self.check_voltage_alert(voltage)
                atak_alert_active, atak_alert_text = self.get_atak_alert_state()
                
                if should_shutdown:
                    self.graceful_shutdown()
                    break
                
                # Update LED state
                self.update_led_state(alert_active, override_active=atak_alert_active)
                
                # Get system info
                date_str = self.system_info.get_raspberry_pi_date()
                time_str = self.system_info.get_raspberry_pi_time()
                cpu_usage = self.system_info.get_raspberry_pi_cpu_usage()
                memory_usage = self.system_info.get_raspberry_pi_memory_usage()
                disk_usage = self.system_info.get_raspberry_pi_disk_usage()
                cpu_temp = self.system_info.get_raspberry_pi_cpu_temperature()
                case_temp = self.expansion.get_temp()
                fan_speeds = self.get_fan_speeds()
                memory_percent, disk_percent = self.normalize_usage_values(memory_usage, disk_usage)
                current_str = self.victron.format_current(current)
                rem_str = self.victron.format_ttg(ttg)
                if self.is_valid_voltage(voltage):
                    power_text = self.format_power_header(float(voltage), current)
                else:
                    power_text = "Shunt Err"
                screen_snapshot = {
                    "date_str": date_str,
                    "time_str": time_str,
                    "cpu_usage": cpu_usage,
                    "memory_percent": memory_percent,
                    "disk_percent": disk_percent,
                    "cpu_temp": cpu_temp,
                    "case_temp": case_temp,
                    "fan_speeds": fan_speeds,
                    "power_text": power_text,
                    "direction_arrow": self.get_charge_direction(current),
                    "voltage": voltage,
                    "current_str": current_str,
                    "soc": soc,
                    "rem_str": rem_str,
                }
                
                # Check if screen needs to switch
                elapsed = time.time() - screen_start_time
                current_screen = self.screen_sequence[current_screen_index]
                screen_duration = self.get_screen_duration(current_screen)
                
                if atak_alert_active:
                    if not previous_atak_alert_active:
                        screen_start_time = time.time()
                    self.update_atak_led_state(True)
                    self.render_atak_alert(atak_alert_text)
                elif alert_active:
                    if previous_atak_alert_active:
                        self.update_atak_led_state(False)
                        screen_start_time = time.time()
                    # Display low-voltage alert instead of normal screens
                    if not previous_alert_active:
                        screen_start_time = time.time()
                    self.oled_ui_low_voltage_alert(voltage)
                else:
                    if previous_atak_alert_active:
                        self.update_atak_led_state(False)
                        screen_start_time = time.time()
                        elapsed = 0
                    if previous_alert_active:
                        screen_start_time = time.time()
                        elapsed = 0
                    if elapsed >= screen_duration:
                        current_screen_index = (current_screen_index + 1) % len(self.screen_sequence)
                        current_screen = self.screen_sequence[current_screen_index]
                        screen_duration = self.get_screen_duration(current_screen)
                        screen_start_time = time.time()
                    
                    self.render_screen(current_screen, screen_snapshot)

                previous_atak_alert_active = atak_alert_active
                previous_alert_active = alert_active
                
                time.sleep(0.3)
            
            except Exception as e:
                print(f"Error in main loop: {e}")
                time.sleep(1)


if __name__ == "__main__":
    task = None
    try:
        task = VictronOLEDTask()
        task.run()
    except KeyboardInterrupt:
        print("\nShutdown requested by user")
    except Exception as e:
        print(f"Fatal error: {e}")
    finally:
        if task:
            task.handle_signal()
