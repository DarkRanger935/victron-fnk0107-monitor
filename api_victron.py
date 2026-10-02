#!/usr/bin/env python3
"""
Victron VE.Direct Protocol Reader
Communicates with Victron SmartShunt via serial VE.Direct interface
"""

import serial
import time
import sys
import threading
import math

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
            'voltage': None,     # Volts
            'current': 0.0,      # Amps (positive = charging, negative = discharging)
            'soc': 0,            # State of Charge %
            'ttg': 0,            # Time remaining from VE.Direct TTG (minutes)
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

    @staticmethod
    def _build_hex_frame(command, register, value=None):
        if command not in (0x7, 0x8):
            raise ValueError("Unsupported VE.Direct HEX command")
        if not 0 <= register <= 0xFFFF:
            raise ValueError("Register must fit in 16 bits")

        body = [command, register & 0xFF, register >> 8, 0]
        payload = ""
        if value is not None:
            if not 0 <= value <= 0xFFFF:
                raise ValueError("Value must fit in 16 bits")
            value_bytes = value.to_bytes(2, byteorder="little")
            body.extend(value_bytes)
            payload = value_bytes.hex().upper()

        checksum = (0x55 - sum(body)) & 0xFF
        return f":{command:X}{register & 0xFF:02X}{register >> 8:02X}00{payload}{checksum:02X}\n"

    @staticmethod
    def _parse_hex_register_response(frame, register):
        frame = frame.strip().upper()
        if len(frame) < 14 or not frame.startswith(":7"):
            return None

        try:
            command = int(frame[1], 16)
            body = [command] + [
                int(frame[index:index + 2], 16)
                for index in range(2, len(frame) - 2, 2)
            ]
            checksum = int(frame[-2:], 16)
            response_register = int(frame[4:6] + frame[2:4], 16)
            payload = frame[8:-2]
            if (0x55 - sum(body)) & 0xFF != checksum or response_register != register:
                return None
            if not payload or len(payload) % 2:
                return None
            return int.from_bytes(bytes.fromhex(payload), byteorder="little")
        except ValueError:
            return None

    def read_hex_register(self, register):
        if self.serial_conn is None:
            raise RuntimeError("Victron serial connection is not open")

        self.serial_conn.write(self._build_hex_frame(0x7, register).encode("ascii"))
        self.serial_conn.flush()
        deadline = time.monotonic() + max(float(self.timeout), 0.1)
        while time.monotonic() < deadline:
            response = self.serial_conn.readline().decode("ascii", errors="ignore")
            value = self._parse_hex_register_response(response, register)
            if value is not None:
                return value
        raise TimeoutError(f"No valid HEX response received for register 0x{register:04X}")

    def write_hex_register(self, register, value):
        if self.serial_conn is None:
            raise RuntimeError("Victron serial connection is not open")

        self.serial_conn.write(self._build_hex_frame(0x8, register, value).encode("ascii"))
        self.serial_conn.flush()

    def read_battery_capacity(self):
        """Read battery capacity from the shunt in whole Ah."""
        capacity_ah = self.read_hex_register(0xED00)
        if not 1 <= capacity_ah <= 0xFFFF:
            raise ValueError(f"Invalid battery capacity returned by shunt: {capacity_ah}")
        return capacity_ah

    def write_battery_capacity(self, capacity_ah):
        """Write battery capacity to the shunt in whole Ah."""
        if isinstance(capacity_ah, bool):
            raise ValueError("Battery capacity must be a whole number of Ah")
        try:
            capacity = int(capacity_ah)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("Battery capacity must be a whole number of Ah") from error
        if capacity != capacity_ah or not 1 <= capacity <= 0xFFFF:
            raise ValueError("Battery capacity must be a whole number between 1 and 65535 Ah")
        self.write_hex_register(0xED00, capacity)
    
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
                    voltage = float(value) / 1000.0
                    self.data['voltage'] = voltage if math.isfinite(voltage) else None
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
                    # Time to go in minutes (-1 = N/A)
                    ttg = int(value)
                    self.data['ttg'] = ttg if ttg > 0 else 0
        except (ValueError, IndexError):
            if key == 'V':
                with self.lock:
                    self.data['voltage'] = None
    
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
        Get Victron TTG value (remaining time in minutes)
        """
        with self.lock:
            return self.data['ttg']
    
    def get_direction(self):
        """
        Get charge direction: 'charging', 'discharging', or 'idle'
        """
        with self.lock:
            return self.data['direction']
    
    def format_ttg(self, minutes):
        """
        Format time to go into readable string
        
        Args:
            minutes (int): Time in minutes
            
        Returns:
            str: Formatted time (e.g., "4h 32m", "45m", "N/A")
        """
        if minutes <= 0:
            return "N/A"
        
        hours = minutes // 60
        remaining_minutes = minutes % 60
        
        if hours > 0:
            return f"{hours}h {remaining_minutes}m"
        else:
            return f"{remaining_minutes}m"
    
    def format_current(self, amps):
        """
        Format current with direction symbol
        
        Args:
            amps (float): Current in Amps
            
        Returns:
            str: Formatted current (e.g., "5.2A ↑", "3.1A ↓")
        """
        if amps > 0:
            return f"{abs(amps):.1f}A ↑"  # Charging (up)
        elif amps < 0:
            return f"{abs(amps):.1f}A ↓"  # Discharging (down)
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
