#!/usr/bin/env python3
"""
Victron VE.Direct Protocol Reader
Communicates with Victron SmartShunt via serial VE.Direct interface
"""

import serial
import time
import sys
import threading

class VictronMonitor:
    def __init__(self, port='/dev/ttyUSB0', baudrate=19200, timeout=1):
        """
        Initialize Victron monitor
        
        Args:
            port (str): Serial port (default /dev/ttyUSB0)
            baudrate (int): Baud rate (default 19200)
            timeout (int): Serial timeout in seconds
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial_conn = None
        self.data = {
            'voltage': 0.0,      # Volts
            'current': 0.0,      # Amps (positive = charging, negative = discharging)
            'soc': 0,            # State of Charge %
            'ttg': 0,            # Time to go (seconds)
            'direction': 'idle'  # 'charging' or 'discharging'
        }
        self.lock = threading.Lock()
        self.running = False
        self.last_update = 0
        
    def connect(self):
        """
        Connect to Victron device via serial
        """
        try:
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE
            )
            print(f"Connected to Victron on {self.port} at {self.baudrate} baud")
            return True
        except serial.SerialException as e:
            print(f"Failed to connect to Victron: {e}")
            return False
    
    def parse_ve_direct_frame(self, line):
        """
        Parse a single VE.Direct frame line
        Format: KEY\tVALUE
        """
        if not line or '\t' not in line:
            return
        
        try:
            key, value = line.split('\t', 1)
            key = key.strip()
            value = value.strip()
            
            with self.lock:
                if key == 'V':
                    # Voltage in mV, convert to V
                    self.data['voltage'] = float(value) / 1000.0
                elif key == 'I':
                    # Current in mA, convert to A
                    current_ma = float(value)
                    self.data['current'] = current_ma / 1000.0
                    # Determine direction
                    if current_ma > 0:
                        self.data['direction'] = 'charging'
                    elif current_ma < 0:
                        self.data['direction'] = 'discharging'
                    else:
                        self.data['direction'] = 'idle'
                elif key == 'SOC':
                    # State of Charge in 0.1% units
                    self.data['soc'] = int(float(value) / 10.0)
                elif key == 'TTG':
                    # Time to go in seconds (-1 = N/A)
                    ttg = int(value)
                    self.data['ttg'] = ttg if ttg > 0 else 0
        except (ValueError, IndexError) as e:
            pass  # Skip malformed lines
    
    def read_loop(self):
        """
        Continuous read loop for VE.Direct frames
        """
        if not self.connect():
            return
        
        self.running = True
        buffer = ""
        
        while self.running:
            try:
                if self.serial_conn and self.serial_conn.in_waiting:
                    byte = self.serial_conn.read(1).decode('ascii', errors='ignore')
                    
                    if byte == '\n':
                        # End of line
                        if buffer:
                            self.parse_ve_direct_frame(buffer)
                            self.last_update = time.time()
                        buffer = ""
                    elif byte == '\r':
                        # Carriage return, ignore
                        pass
                    else:
                        buffer += byte
                else:
                    time.sleep(0.01)  # Avoid busy waiting
            except Exception as e:
                print(f"Error reading from Victron: {e}")
                time.sleep(1)
    
    def start(self):
        """
        Start reading in background thread
        """
        if not self.running:
            thread = threading.Thread(target=self.read_loop, daemon=True)
            thread.start()
    
    def stop(self):
        """
        Stop reading and close connection
        """
        self.running = False
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
        print("Victron connection closed")
    
    def get_data(self):
        """
        Get current Victron data (thread-safe)
        
        Returns:
            dict: Current data snapshot
        """
        with self.lock:
            return dict(self.data)
    
    def get_voltage(self):
        """
        Get current voltage in Volts
        """
        with self.lock:
            return self.data['voltage']
    
    def get_current(self):
        """
        Get current in Amps (positive = charging, negative = discharging)
        """
        with self.lock:
            return self.data['current']
    
    def get_soc(self):
        """
        Get State of Charge percentage
        """
        with self.lock:
            return self.data['soc']
    
    def get_ttg(self):
        """
        Get Time To Go (estimated runtime in seconds)
        """
        with self.lock:
            return self.data['ttg']
    
    def get_direction(self):
        """
        Get charge direction: 'charging', 'discharging', or 'idle'
        """
        with self.lock:
            return self.data['direction']
    
    def format_ttg(self, seconds):
        """
        Format time to go into readable string
        
        Args:
            seconds (int): Time in seconds
            
        Returns:
            str: Formatted time (e.g., "4h 32m", "45m", "N/A")
        """
        if seconds <= 0:
            return "N/A"
        
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        
        if hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"
    
    def format_current(self, amps):
        """
        Format current with direction symbol
        
        Args:
            amps (float): Current in Amps
            
        Returns:
            str: Formatted current (e.g., "5.2A ↓", "-3.1A ↑")
        """
        if amps > 0:
            return f"{abs(amps):.1f}A ↓"  # Charging (down)
        elif amps < 0:
            return f"{abs(amps):.1f}A ↑"  # Discharging (up)
        else:
            return "0.0A"


if __name__ == '__main__':
    # Test harness
    monitor = VictronMonitor()
    monitor.start()
    
    try:
        for i in range(10):
            time.sleep(1)
            data = monitor.get_data()
            print(f"V={data['voltage']:.1f}V I={data['current']:.1f}A SOC={data['soc']}% TTG={monitor.format_ttg(data['ttg'])} Dir={data['direction']}")
    except KeyboardInterrupt:
        print("\nTest stopped")
    finally:
        monitor.stop()
