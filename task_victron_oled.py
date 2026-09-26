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
from datetime import datetime, timedelta

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
        self.font_size = 12
        self.system_screens = ("date_time", "utilization", "fans", "temperatures")
        self.screen_sequence = self.system_screens + ("victron",)
        
        # Load config
        victron_config = self.config_manager.get_value('Victron', 'port') or {}
        oled_config = self.config_manager.get_section('OLED') or {}
        
        self.victron_port = self.config_manager.get_value('Victron', 'port') or '/dev/ttyUSB0'
        self.low_voltage_threshold = self.config_manager.get_value('Victron', 'low_voltage_threshold') or 12.8
        self.critical_voltage_threshold = self.config_manager.get_value('Victron', 'critical_voltage_threshold') or 12.7
        
        self.screen1_duration = self.config_manager.get_value('OLED', 'screen1', {}).get('display_time', 35.0) if self.config_manager.get_value('OLED', 'screen1') else 35.0
        self.screen2_duration = self.config_manager.get_value('OLED', 'screen2', {}).get('display_time', 35.0) if self.config_manager.get_value('OLED', 'screen2') else 35.0
        self.system_screen_duration = max(5.0, self.screen1_duration / max(1, len(self.system_screens)))
        
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
        
        atexit.register(self.handle_signal)
        signal.signal(signal.SIGTERM, self.handle_signal)
        signal.signal(signal.SIGINT, self.handle_signal)
    
    def handle_signal(self, signum=None, frame=None):
        """Handle shutdown signals"""
        print("\nShutdown signal received")
        self.running = False
        
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
        if voltage < self.critical_voltage_threshold:
            # Critical shutdown
            return True, True
        elif voltage <= self.low_voltage_threshold:
            # Low voltage alert
            return True, False
        else:
            # Normal
            return False, False
    
    def update_led_state(self, alert_active):
        """
        Update LED color based on alert state
        """
        current_time = time.time()
        
        if alert_active:
            # Flash red/blue every 1 second
            if self.last_led_mode != 1 or current_time - self.last_alert_toggle >= 1.0:
                self.alert_color_toggle = not self.alert_color_toggle
                self.last_alert_toggle = current_time
            
            if self.alert_color_toggle:
                self._set_led_state(1, (255, 0, 0))  # Red
            else:
                self._set_led_state(1, (0, 0, 255))  # Blue
        else:
            # Normal cyan follow mode
            self._set_led_state(2, (0, 6, 6))  # Cyan follow mode
    
    def _set_led_state(self, mode, color):
        """Update LED mode/color only when the requested state changes."""
        if self.last_led_mode != mode:
            self.expansion.set_led_mode(mode)
            self.last_led_mode = mode
        
        if self.last_led_color != color:
            self.expansion.set_all_led_color(*color)
            self.last_led_color = color
    
    def get_direction_arrow(self, direction):
        """Return arrow matching the current power-flow direction."""
        if direction == 'charging':
            return '↑'
        if direction == 'discharging':
            return '↓'
        return '→'
    
    def format_power_header(self, voltage, current, direction):
        """Format power and flow direction for the Victron header."""
        watts = abs(voltage * current)
        if watts < 10:
            power_text = f"{watts:.1f}W"
        else:
            power_text = f"{watts:.0f}W"
        return f"{power_text} {self.get_direction_arrow(direction)}"
    
    def get_screen_duration(self, screen_name):
        """Return the configured duration for a given screen."""
        if screen_name == "victron":
            return self.screen2_duration
        return self.system_screen_duration
    
    def oled_ui_date_time(self, date_str, time_str):
        """Display the date and time on a dedicated screen."""
        self.oled.clear()
        self.oled.draw_rectangle((0, 0, self.oled.width-1, self.oled.height-1), outline="white")
        self.oled.draw_text("DATE / TIME", position=((0, 4), (128, 16)), directory="center", offset=(0, 0), font_size=11)
        self.oled.draw_text(time_str, position=((0, 20), (128, 40)), directory="center", offset=(0, 0), font_size=18)
        self.oled.draw_text(date_str, position=((0, 46), (128, 58)), directory="center", offset=(0, 0), font_size=12)
        self.oled.show()
    
    def oled_ui_system_stats(self, cpu_usage, memory_usage, disk_usage):
        """
        Display system hardware utilization with pie charts
        """
        self.oled.clear()
        
        # Draw border
        self.oled.draw_rectangle((0, 0, self.oled.width-1, self.oled.height-1), outline="white")
        self.oled.draw_text("UTILIZATION", position=((0, 4), (128, 16)), directory="center", offset=(0, 0), font_size=11)
        
        # CPU, MEM, DISK pie charts
        # CPU pie (left)
        self.oled.draw_text("CPU", position=((0, 16), (42, 24)), directory="center", offset=(0, 0), font_size=10)
        self.oled.draw_circle_with_percentage((21, 37), 12, int(cpu_usage), outline="white", fill="white")
        self.oled.draw_text(f"{int(cpu_usage)}%", position=((0, 50), (42, 60)), directory="center", offset=(0, 0), font_size=10)
        
        # MEM pie (center)
        self.oled.draw_text("MEM", position=((43, 16), (85, 24)), directory="center", offset=(0, 0), font_size=10)
        self.oled.draw_circle_with_percentage((64, 37), 12, int(memory_usage), outline="white", fill="white")
        self.oled.draw_text(f"{int(memory_usage)}%", position=((43, 50), (85, 60)), directory="center", offset=(0, 0), font_size=10)
        
        # DISK pie (right)
        self.oled.draw_text("DSK", position=((86, 16), (128, 24)), directory="center", offset=(0, 0), font_size=10)
        self.oled.draw_circle_with_percentage((107, 37), 12, int(disk_usage), outline="white", fill="white")
        self.oled.draw_text(f"{int(disk_usage)}%", position=((86, 50), (128, 60)), directory="center", offset=(0, 0), font_size=10)
        
        self.oled.show()
    
    def oled_ui_fan_speeds(self, fan_speeds):
        """Display fan speeds on their own screen."""
        self.oled.clear()
        self.oled.draw_rectangle((0, 0, self.oled.width-1, self.oled.height-1), outline="white")
        self.oled.draw_text("FAN SPEEDS", position=((0, 4), (128, 16)), directory="center", offset=(0, 0), font_size=11)
        
        if len(fan_speeds) >= 3:
            fan_layout = [
                ("F1", fan_speeds[0], ((0, 16), (42, 60)), (21, 37)),
                ("F2", fan_speeds[1], ((43, 16), (85, 60)), (64, 37)),
                ("F3", fan_speeds[2], ((86, 16), (128, 60)), (107, 37)),
            ]
        elif len(fan_speeds) >= 2:
            fan_layout = [
                ("F1", fan_speeds[0], ((0, 16), (64, 60)), (32, 37)),
                ("F2", fan_speeds[1], ((64, 16), (128, 60)), (96, 37)),
            ]
        elif fan_speeds:
            fan_layout = [
                ("F1", fan_speeds[0], ((0, 16), (128, 60)), (64, 37)),
            ]
        else:
            self.oled.draw_text("No fan data", position=((0, 26), (128, 40)), directory="center", offset=(0, 0), font_size=12)
            self.oled.show()
            return
        
        for label, speed, text_box, center in fan_layout:
            x1, y1 = text_box[0]
            x2, y2 = text_box[1]
            self.oled.draw_text(label, position=((x1, y1), (x2, y1 + 8)), directory="center", offset=(0, 0), font_size=10)
            self.oled.draw_circle_with_percentage(center, 12, int(speed), outline="white", fill="white")
            self.oled.draw_text(f"{int(speed)}%", position=((x1, y2 - 10), (x2, y2)), directory="center", offset=(0, 0), font_size=10)
        
        self.oled.show()
    
    def oled_ui_temperatures(self, cpu_temp, case_temp):
        """Display temperature readings on their own screen."""
        self.oled.clear()
        self.oled.draw_rectangle((0, 0, self.oled.width-1, self.oled.height-1), outline="white")
        self.oled.draw_text("TEMPERATURES", position=((0, 4), (128, 16)), directory="center", offset=(0, 0), font_size=11)
        self.oled.draw_text("CPU", position=((0, 20), (64, 30)), directory="center", offset=(0, 0), font_size=12)
        self.oled.draw_text(f"{int(cpu_temp)}C", position=((0, 34), (64, 50)), directory="center", offset=(0, 0), font_size=17)
        self.oled.draw_line(((64, 18), (64, 56)), fill="white")
        self.oled.draw_text("CASE", position=((64, 20), (128, 30)), directory="center", offset=(0, 0), font_size=12)
        self.oled.draw_text(f"{int(case_temp)}C", position=((64, 34), (128, 50)), directory="center", offset=(0, 0), font_size=17)
        
        self.oled.show()
    
    def oled_ui_victron_stats(self, power_text, voltage, current_str, soc, rem_str):
        """
        Display Victron battery statistics
        """
        self.oled.clear()
        
        # Draw border and dividers
        self.oled.draw_rectangle((0, 0, self.oled.width-1, self.oled.height-1), outline="white")
        self.oled.draw_line(((0, 16), (self.oled.width-1, 16)), fill="white")
        
        # Header
        self.oled.draw_text(power_text, position=((0, 0), (128, 16)), directory="center", offset=(0, 2), font_size=12)
        
        # Voltage
        self.oled.draw_text(f"Voltage: {voltage:.1f}V", position=((0, 18), (128, 30)), directory="left", offset=(2, 0), font_size=11)
        
        # Current
        self.oled.draw_text(f"Current: {current_str}", position=((0, 30), (128, 42)), directory="left", offset=(2, 0), font_size=11)
        
        # SOC
        self.oled.draw_text(f"SOC: {soc}%", position=((0, 42), (128, 54)), directory="left", offset=(2, 0), font_size=11)
        
        # Remaining time
        self.oled.draw_text(f"Rem: {rem_str}", position=((0, 54), (128, 64)), directory="left", offset=(2, 0), font_size=11)
        
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
    
    def graceful_shutdown(self):
        """
        Perform graceful shutdown when voltage drops below critical threshold
        """
        print("\n" + "="*50)
        print("CRITICAL VOLTAGE - INITIATING GRACEFUL SHUTDOWN")
        print("="*50)
        
        # Display shutdown message on OLED
        self.oled.clear()
        self.oled.draw_rectangle((0, 0, self.oled.width-1, self.oled.height-1), outline="white")
        self.oled.draw_text("SHUTDOWN", position=((0, 20), (128, 30)), directory="center", offset=(0, 0), font_size=14)
        self.oled.draw_text("Critical Voltage", position=((0, 35), (128, 45)), directory="center", offset=(0, 0), font_size=11)
        self.oled.draw_text("System halting...", position=((0, 50), (128, 60)), directory="center", offset=(0, 0), font_size=10)
        self.oled.show()
        
        # Turn off LED
        self.expansion.set_all_led_color(0, 0, 0)
        self.expansion.set_led_mode(0)
        
        time.sleep(2)
        
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
        
        screen_start_time = time.time()
        current_screen_index = 0
        
        while self.running:
            try:
                # Get Victron data
                voltage = self.victron.get_voltage()
                current = self.victron.get_current()
                soc = self.victron.get_soc()
                ttg = self.victron.get_ttg()
                direction = self.victron.get_direction()
                
                # Check voltage
                alert_active, should_shutdown = self.check_voltage_alert(voltage)
                
                if should_shutdown:
                    self.graceful_shutdown()
                    break
                
                # Update LED state
                self.update_led_state(alert_active)
                
                # Get system info
                date_str = self.system_info.get_raspberry_pi_date()
                time_str = self.system_info.get_raspberry_pi_time()
                cpu_usage = self.system_info.get_raspberry_pi_cpu_usage()
                memory_usage = self.system_info.get_raspberry_pi_memory_usage()
                disk_usage = self.system_info.get_raspberry_pi_disk_usage()
                cpu_temp = self.system_info.get_raspberry_pi_cpu_temperature()
                case_temp = self.expansion.get_temp()
                fan_duty = self.expansion.get_fan_duty()
                fan_speeds = [d / 255.0 * 100 for d in (fan_duty if isinstance(fan_duty, list) else [fan_duty])]
                memory_percent = memory_usage[0] if isinstance(memory_usage, list) else memory_usage
                disk_percent = disk_usage[0] if isinstance(disk_usage, list) else disk_usage
                current_str = self.victron.format_current(current)
                rem_str = self.victron.format_ttg(ttg)
                power_text = self.format_power_header(voltage, current, direction)
                
                # Check if screen needs to switch
                elapsed = time.time() - screen_start_time
                current_screen = self.screen_sequence[current_screen_index]
                screen_duration = self.get_screen_duration(current_screen)
                
                if alert_active:
                    # Display alert instead of normal screens
                    self.oled_ui_low_voltage_alert(voltage)
                else:
                    if elapsed >= screen_duration:
                        current_screen_index = (current_screen_index + 1) % len(self.screen_sequence)
                        current_screen = self.screen_sequence[current_screen_index]
                        screen_duration = self.get_screen_duration(current_screen)
                        screen_start_time = time.time()
                    
                    if current_screen == "date_time":
                        self.oled_ui_date_time(date_str, time_str)
                    elif current_screen == "utilization":
                        self.oled_ui_system_stats(cpu_usage, memory_percent, disk_percent)
                    elif current_screen == "fans":
                        self.oled_ui_fan_speeds(fan_speeds)
                    elif current_screen == "temperatures":
                        self.oled_ui_temperatures(cpu_temp, case_temp)
                    else:
                        self.oled_ui_victron_stats(power_text, voltage, current_str, soc, rem_str)
                
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
