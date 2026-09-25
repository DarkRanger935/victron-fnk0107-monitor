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
        self.font_size = 12
        
        # Load config
        victron_config = self.config_manager.get_value('Victron', 'port') or {}
        oled_config = self.config_manager.get_section('OLED') or {}
        
        self.victron_port = self.config_manager.get_value('Victron', 'port') or '/dev/ttyUSB0'
        self.low_voltage_threshold = self.config_manager.get_value('Victron', 'low_voltage_threshold') or 12.8
        self.critical_voltage_threshold = self.config_manager.get_value('Victron', 'critical_voltage_threshold') or 12.7
        
        self.screen1_duration = self.config_manager.get_value('OLED', 'screen1', {}).get('display_time', 35.0) if self.config_manager.get_value('OLED', 'screen1') else 35.0
        self.screen2_duration = self.config_manager.get_value('OLED', 'screen2', {}).get('display_time', 35.0) if self.config_manager.get_value('OLED', 'screen2') else 35.0
        
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
            if current_time - self.last_alert_toggle >= 1.0:
                self.alert_color_toggle = not self.alert_color_toggle
                self.last_alert_toggle = current_time
            
            if self.alert_color_toggle:
                self.expansion.set_all_led_color(255, 0, 0)  # Red
            else:
                self.expansion.set_all_led_color(0, 0, 255)  # Blue
        else:
            # Normal cyan follow mode
            self.expansion.set_led_mode(2)  # Follow mode
            self.expansion.set_all_led_color(0, 6, 6)  # Cyan
    
    def oled_ui_system_stats(self, date_str, time_str, cpu_usage, memory_usage, disk_usage, cpu_temp, case_temp, fan_speeds):
        """
        Display system hardware statistics with pie charts
        """
        self.oled.clear()
        
        # Draw border
        self.oled.draw_rectangle((0, 0, self.oled.width-1, self.oled.height-1), outline="white")
        self.oled.draw_line(((0, 16), (self.oled.width-1, 16)), fill="white")
        self.oled.draw_line(((0, 48), (self.oled.width-1, 48)), fill="white")
        
        # Row 1: Date and Time
        self.oled.draw_text(f"{date_str}", position=((0, 0), (128, 8)), directory="center", offset=(0, 0), font_size=10)
        self.oled.draw_text(f"{time_str}", position=((0, 8), (128, 16)), directory="center", offset=(0, 0), font_size=10)
        
        # Row 2: CPU, MEM, DISK pie charts
        # CPU pie (left)
        self.oled.draw_circle_with_percentage((21, 32), 14, int(cpu_usage), outline="white", fill="white")
        self.oled.draw_text(f"{int(cpu_usage)}%", position=((0, 38), (42, 48)), directory="center", offset=(0, 0), font_size=10)
        
        # MEM pie (center)
        self.oled.draw_circle_with_percentage((64, 32), 14, int(memory_usage), outline="white", fill="white")
        self.oled.draw_text(f"{int(memory_usage)}%", position=((43, 38), (85, 48)), directory="center", offset=(0, 0), font_size=10)
        
        # DISK pie (right)
        self.oled.draw_circle_with_percentage((107, 32), 14, int(disk_usage), outline="white", fill="white")
        self.oled.draw_text(f"{int(disk_usage)}%", position=((86, 38), (128, 48)), directory="center", offset=(0, 0), font_size=10)
        
        # Row 3: Temperatures and fan speeds
        temp_text = f"CPU:{cpu_temp}C Case:{case_temp}C"
        self.oled.draw_text(temp_text, position=((0, 48), (128, 56)), directory="center", offset=(0, 0), font_size=9)
        
        fan_text = f"Fans:{int(fan_speeds[0])}% {int(fan_speeds[1])}% {int(fan_speeds[2])}%" if len(fan_speeds) >= 3 else f"Fans:{int(fan_speeds[0])}% {int(fan_speeds[1])}%"
        self.oled.draw_text(fan_text, position=((0, 56), (128, 64)), directory="center", offset=(0, 0), font_size=9)
        
        self.oled.show()
    
    def oled_ui_victron_stats(self, voltage, current_str, soc, runtime_str):
        """
        Display Victron battery statistics
        """
        self.oled.clear()
        
        # Draw border and dividers
        self.oled.draw_rectangle((0, 0, self.oled.width-1, self.oled.height-1), outline="white")
        self.oled.draw_line(((0, 16), (self.oled.width-1, 16)), fill="white")
        
        # Title
        self.oled.draw_text("BATTERY MONITOR", position=((0, 0), (128, 16)), directory="center", offset=(0, 2), font_size=12)
        
        # Voltage
        self.oled.draw_text(f"Voltage: {voltage:.1f}V", position=((0, 18), (128, 30)), directory="left", offset=(2, 0), font_size=11)
        
        # Current
        self.oled.draw_text(f"Current: {current_str}", position=((0, 30), (128, 42)), directory="left", offset=(2, 0), font_size=11)
        
        # SOC
        self.oled.draw_text(f"SOC: {soc}%", position=((0, 42), (128, 54)), directory="left", offset=(2, 0), font_size=11)
        
        # Runtime
        self.oled.draw_text(f"Runtime: {runtime_str}", position=((0, 54), (128, 64)), directory="left", offset=(2, 0), font_size=11)
        
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
        current_screen = 0  # 0 = system stats, 1 = victron stats
        
        while self.running:
            try:
                # Get Victron data
                voltage = self.victron.get_voltage()
                current = self.victron.get_current()
                soc = self.victron.get_soc()
                ttg = self.victron.get_ttg()
                
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
                
                # Check if screen needs to switch
                elapsed = time.time() - screen_start_time
                screen_duration = self.screen1_duration if current_screen == 0 else self.screen2_duration
                
                if alert_active:
                    # Display alert instead of normal screens
                    self.oled_ui_low_voltage_alert(voltage)
                elif elapsed >= screen_duration:
                    # Switch screen
                    current_screen = 1 - current_screen
                    screen_start_time = time.time()
                    
                    if current_screen == 0:
                        # System stats
                        self.oled_ui_system_stats(date_str, time_str, cpu_usage, memory_usage[0], disk_usage[0], 
                                                 int(cpu_temp), int(case_temp), fan_speeds)
                    else:
                        # Victron stats
                        current_str = self.victron.format_current(current)
                        runtime_str = self.victron.format_ttg(ttg)
                        self.oled_ui_victron_stats(voltage, current_str, soc, runtime_str)
                else:
                    # Display current screen
                    if current_screen == 0:
                        self.oled_ui_system_stats(date_str, time_str, cpu_usage, memory_usage[0], disk_usage[0],
                                                 int(cpu_temp), int(case_temp), fan_speeds)
                    else:
                        current_str = self.victron.format_current(current)
                        runtime_str = self.victron.format_ttg(ttg)
                        self.oled_ui_victron_stats(voltage, current_str, soc, runtime_str)
                
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
