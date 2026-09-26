# Victron FNK0107 Power Monitor

A comprehensive power monitoring system for Raspberry Pi 5 that seamlessly integrates Victron battery monitoring with FNK0107 case control, OLED display, and ARGB LED indicators.

## 🎯 Features

### Victron Monitoring
- **Real-time power metrics**: Voltage, current (amps), charge/discharge direction
- **Battery state**: State of Charge (SOC), estimated runtime remaining
- **VE.Direct serial communication**: Reliable data acquisition from Victron 300A shunt monitor

### System Display (35-second cycle each)
- **Pi Hardware Stats Screen** (35 seconds)
  - CPU, Memory, Disk usage as pie charts
  - CPU and case temperature (°C)
  - Fan speeds as percentage
  - Date and time display

- **Victron Stats Screen** (35 seconds)
  - Voltage (V)
  - Current (A) with direction (charging/discharging)
  - State of Charge (%)
  - Estimated runtime

### Intelligent Alerts
- **Low Voltage Alert** (≤12.8V)
  - OLED displays alert overlay
  - ARGB LEDs flash alternating red (255,0,0) and blue (0,0,255) every second
  - Persists until voltage recovers above 12.8V

- **Critical Shutdown** (<12.7V)
  - Automatic graceful system shutdown
  - Prevents data corruption

### Normal Operation
- **ARGB LED Mode**: Follow mode with cyan (0,6,6) color
- **Continuous Monitoring**: Real-time voltage polling
- **Service Mode**: Runs as systemd service for auto-startup

## 📋 Requirements

### Hardware
- Raspberry Pi 5 (64-bit)
- Freenove FNK0107 Computer Case Kit Pro
- Victron 300A SmartShunt Monitor
- VE.Direct to USB cable (connected to Pi)
- Raspberry Pi OS Bookworm 64-bit

### System Packages (Bookworm)
```bash
python3-serial
python3-pil
python3-psutil
python3-smbus
i2c-tools
```

## 🚀 Installation

### 1. Clone Repository
```bash
cd ~
git clone https://github.com/DarkRanger935/victron-fnk0107-monitor.git
cd victron-fnk0107-monitor
```

### 2. Install System Dependencies (Bookworm)
```bash
sudo apt-get update
sudo apt-get install -y $(grep -Ev '^(#|$)' requirements.txt | tr '\n' ' ')

# Make repository modules importable from any working directory
# Run this from the repository root (after `cd victron-fnk0107-monitor`)
python3 - <<'PY'
from pathlib import Path
import site

repo_path = Path.cwd()
user_site = Path(site.getusersitepackages())
user_site.mkdir(parents=True, exist_ok=True)
(user_site / "victron_fnk0107_monitor.pth").write_text(f"{repo_path}\n", encoding="utf-8")
print(f"Created {user_site / 'victron_fnk0107_monitor.pth'} -> {repo_path}")
PY

# Note: this creates a persistent user-site import path entry.
# This applies to the system-Python flow documented in this README.
# If you move/delete the repo, remove it with:
rm -f "$(python3 -m site --user-site)/victron_fnk0107_monitor.pth"
```

**Why system packages?**
- ✅ No `externally-managed-environment` conflicts
- ✅ Pre-compiled for Raspberry Pi ARM64
- ✅ Auto-updated with system patches
- ✅ No virtual environment needed

### 3. Enable I2C Interface
```bash
sudo raspi-config
# Navigate to: Interface Options → I2C → Enable
```

### 4. Verify VE.Direct Connection
```bash
ls -la /dev/serial/by-id/
# Should show: usb-VictronEnergy_BV_VE_Direct_cable_VEAWDPFF-if00-port0
```

### 4.1 Verify Python Module Imports
```bash
python3 -c "import api_expansion, api_oled, api_victron, api_systemInfo, api_systeminfo; print('api_* imports OK')"
```

### 5. Verify I2C Devices
```bash
sudo i2cdetect -y 1
# Should show: 0x3c (OLED) and 0x21 (FNK0107 expansion board)
```

### 6. Update Configuration (Optional)
Edit `app_config.json`:
```json
{
  "Victron": {
    "port": "/dev/serial/by-id/usb-VictronEnergy_BV_VE_Direct_cable_VEAWDPFF-if00-port0",
    "baudrate": 19200,
    "timeout": 1,
    "low_voltage_threshold": 12.8,
    "critical_voltage_threshold": 12.7
  },
  "OLED": {
    "screen1_duration": 35,
    "screen2_duration": 35
  }
}
```

## 🔧 Quick Start

### Manual Execution
```bash
cd ~/victron-fnk0107-monitor
python3 task_victron_oled.py
```

### Install as System Service
```bash
sudo cp systemd/victron-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable victron-monitor.service
sudo systemctl start victron-monitor.service
```

### Check Service Status
```bash
sudo systemctl status victron-monitor.service
```

### View Live Logs
```bash
sudo journalctl -u victron-monitor.service -f
```

## 📁 Project Structure

```
victron-fnk0107-monitor/
├── README.md                      # This file
├── TESTING.md                     # Comprehensive testing guide
├── requirements.txt               # System packages (apt)
├── app_config.json               # Configuration file
├── api_victron.py                # Victron shunt communication
├── api_expansion.py              # FNK0107 case control (from Freenove)
├── api_json.py                   # Configuration management
├── api_systemInfo.py             # Pi system information (from Freenove)
├── api_systeminfo.py             # Lowercase compatibility import shim
├── api_oled.py                   # OLED display (from Freenove)
├── task_victron_oled.py          # Main integrated task
├── task_led.py                   # LED control daemon
├── task_fan.py                   # Fan control daemon
├── task_manager.py               # Task orchestration
├── systemd/
│   └── victron-monitor.service   # Systemd service file
└── data/
    └── app_config.json           # Runtime configuration
```

## 🔌 Serial Communication

### Victron VE.Direct Protocol
- **Baud Rate**: 19200
- **Data Bits**: 8
- **Stop Bits**: 1
- **Parity**: None
- **Default Port**: `/dev/serial/by-id/usb-VictronEnergy_BV_VE_Direct_cable_VEAWDPFF-if00-port0`

Messages parsed:
- `V` - Voltage (millivolts)
- `I` - Current (milliamps, positive=charging, negative=discharging)
- `SOC` - State of Charge (%)
- `TTG` - Time to go (estimated runtime in seconds)

## 🎨 Display Modes

### LED Behavior

**Normal Operation**
- Color: Cyan (0, 6, 6) in Follow Mode
- Indicates healthy system operation

**Low Voltage Alert (12.8V ≤ V < 12.7V)**
- Flash pattern: Red ↔ Blue
- Frequency: 1 Hz (1 second per color)
- Indicates: Immediate attention needed
- Action: Manual check/intervention recommended
- OLED Message: "Shutdown Imminent!"

**Critical Voltage (<12.7V)**
- LED pattern: Off (system shutting down)
- Action: Automatic graceful shutdown initiated

## 🖥️ OLED Screen Layout

### Screen 1: System Hardware (35 seconds)
```
┌────────────────────┐
│    Date & Time     │
│  12:34:56 Mon     │
├────────────────────┤
│ CPU MEM DISK      │
│  ◯   ◯   ◯        │
│ 20% 45% 75%       │
├────────────────────┤
│ CPU: 42°C Case:38°C│
│ Fans: 65% 58% 72% │
└────────────────────┘
```

### Screen 2: Victron Battery (35 seconds)
```
┌────────────────────┐
│ BATTERY MONITOR    │
├────────────────────┤
│ Voltage: 13.2V    │
│ Current: 5.2A⚡   │
│ SOC: 87%          │
│ Runtime: 4h 32m   │
└────────────────────┘
```

### Alert Overlay: Low Voltage (when V ≤ 12.8V)
```
┌────────────────────┐
│   ⚠️ LOW VOLTAGE ⚠️   │
│                    │
│  V: 12.7V         │
│  Action Required   │
│  Shutdown Imminent!│
└────────────────────┘
```

## 🐛 Troubleshooting

### VE.Direct Not Found
```bash
# Check connected USB devices
lsusb
# Should show Victron device

# Check serial port
ls -la /dev/serial/by-id/
# Should show usb-VictronEnergy_BV_VE_Direct_cable_VEAWDPFF-if00-port0
```

### OLED Not Displaying
```bash
# Check I2C devices
sudo i2cdetect -y 1
# Should show 0x3c (OLED) and 0x21 (FNK0107)
```

### Service Not Starting
```bash
# Check for errors
sudo systemctl status victron-monitor.service
sudo journalctl -u victron-monitor.service -n 50
```

### High CPU Usage
- Reduce polling frequency in `app_config.json`
- Check for stuck threads in logs

## ⚙️ Advanced Configuration

### Voltage Thresholds
Edit `app_config.json`:
```json
{
  "Victron": {
    "low_voltage_threshold": 12.8,      # Alert threshold
    "critical_voltage_threshold": 12.7  # Shutdown threshold
  }
}
```

### Display Timing
```json
{
  "OLED": {
    "screen1_duration": 35,    # Pi stats display time
    "screen2_duration": 35     # Victron stats display time
  }
}
```

### LED Modes
- **Normal**: Follow mode cyan (0, 6, 6)
- **Alert**: Flashing red/blue
- **Critical**: Off

## 🔐 Security Notes

- Service runs as `pi` user (customize in service file)
- VE.Direct data is unencrypted on local serial bus
- Consider restricting physical access to USB connections
- Logs contain voltage/current data (sensitive for mobile power systems)

## 📝 License

This project integrates code from:
- **Freenove** ([FNK0107 repository](https://github.com/Freenove/Freenove_Computer_Case_Kit_Pro_for_Raspberry_Pi)) - Licensed under Freenove's terms
- **Victron Energy** - VE.Direct protocol documentation

Custom integration and Victron monitoring code: MIT License

## 🤝 Contributing

Issues, feature requests, and pull requests welcome!

## 📚 References

- [Victron VE.Direct Protocol](https://www.victronenergy.com/live/VE.Direct_Protocol:Home)
- [Freenove FNK0107 Docs](https://docs.freenove.com/projects/fnk0107/en/latest/)
- [Raspberry Pi GPIO/I2C](https://www.raspberrypi.com/documentation/)

## ⚡ Status

**✅ RELEASE v0.1.0 - Available Now**

### What's Included
- ✅ Victron VE.Direct integration
- ✅ Real-time voltage, current, SOC monitoring
- ✅ Low voltage alert system (≤12.8V)
- ✅ Critical shutdown (≤12.7V)
- ✅ OLED display with system stats (pie charts) and battery info
- ✅ ARGB LED alert flashing (red/blue alternating)
- ✅ Systemd service for auto-startup
- ✅ Full configuration management

### Installation Quick Links
- [Installation Guide](#-installation)
- [Deployment Instructions](#-installation)
- [Troubleshooting](#-troubleshooting)

### Roadmap
- [x] v0.1.0 - Core Victron integration (✅ Released)
- [ ] v0.2.0 - Web dashboard
- [ ] v0.3.0 - Data logging & history
- [ ] v0.4.0 - Mobile app integration
- [ ] v1.0.0 - Production stable release

---

**Questions?** Open an issue or check the [Wiki](https://github.com/DarkRanger935/victron-fnk0107-monitor/wiki)

**Release Date**: 2026-09-26  
**Current Version**: v0.1.0  
**Repository**: [DarkRanger935/victron-fnk0107-monitor](https://github.com/DarkRanger935/victron-fnk0107-monitor)
