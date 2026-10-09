# Victron FNK0107 Power & Atak Monitor

A very resource-efficient power and Atak monitoring system for Raspberry Pi 5 that  integrates Victron battery monitoring (Smart shunt 300A) and Atak emergency alerts with FNK0107 case control, OLED display, and ARGB LED indicators.  This repo incorporates the relevant Freenove & Victron libraries to provide all described features, no additional software from Freenove need be installed.  Atak Emergency monitoring tested and validated with a standard docker install of Atak-civ version 5.6 (the installation of which is outside the scope of this document, see documentation on tak.gov for that). PI Statistics that are available are complimented with key power statistics from the Smart shunt, based on the assumption the monitored battery is the one powering the raspberry PI.  Note that the Time Remaining and State-of-Charge (SOC) come straight from the Smart shunt, which factors in the Discharge Floor configured in the shunt.  This service, however, only actively evaluates the battery voltage against the voltage thresholds in the configuration JSON file.  if the voltage falls below the warning threshold, the OLED display will show a low-voltage warning, and will flash the case OLED lights at full brightness with an alternating pattern (red and blue by default).  if the voltage falls below the configured Critical threshold, an "imminent shutdown" alert will briefly display on the case OLED display, then a safe, orderly shutdown of the PI 5 will occur.
Note that if the load on the power system is reduced (which will raise the system voltage and remaining battery life), then the warning on the OLED display and ARGB case lights will clear and return to their configured normal states.  However, if a critical voltage threshold is crossed, the imminent shutdown is "baked-in", the power monitoring will cease, and the shutdown will occur regardless of any subsequent improvement in voltage. Emergency Alerts from Atak (such as CasEvac or In Contact) will also flash the case ARGB lights (red and green by default), and display relevant details on the OLED display, and clear if the alert is removed in Atak.  ARGB colour and animation patterns are all fully configurable in the JSON file.

## 🎯 Features

### Victron Monitoring
- **Real-time power metrics**: Voltage, current (amps), Power (Watts), charge/discharge direction.  Direction is displayed as either an 'up' arrow (charging) or 'down'arrow (discharging.)
- **Battery state**: State of Charge (SOC), Victron-reported time remaining
- **VE.Direct serial communication**: Reliable data acquisition from Victron 300A shunt monitor, using a .VEdirect-to-USB cable.
- Planned Feature: ability to change certain configuration parameters (total battery capacity in AH, Discharge Floor) for the SmartShunt or enable/disable Bluetooth simply via an edit of the service configuration JSON and restarting the service; do not attempt to use it at this time, as the register locations needed for the 300A SmartShunt have yet to be confirmed by Victron.  this feature will be very handy to minimise power losses from Bluetooth if the SmartShunt and .VEdirect cable are packed into a densely-wired case that you don't want to have to open regularly.
### Atak Emergency Alert Monitoring
- **Real-time power Atak Emergency Alert monitoring**: The OLED display will show the type of alert, the call sign of the sender, and their MGRS coordinates for all Atak Emergency alerts until they are cleared in Atak.

### System Display
- **Date / Time Screen**
- **Utilization Screen**: CPU, Memory, Disk pie charts
- **Fan Screen**: CPU and case-fan PWM pie charts
- **Temperature Screen**: CPU and case temperatures
- **Victron Screen**: Power header, voltage, current, SOC, and time remaining

### Intelligent Alerts
- **Low Voltage Alert** (≤12.8V default)
  - OLED displays alert overlay
  - ARGB LEDs flash alternating red (255,0,0) and blue (0,0,255) every second
  - Persists until voltage recovers above configured warning level (12.8v default).

- **ATAK Emergency Alert** (optional)
  - Receives emergency and CASEVAC details from a local ATAK monitor over a Unix-domain socket
  - Overrides the normal OLED rotation with a scrolling alert marquee
  - Flashes the ARGB LEDs red and green until ATAK reports the emergency cleared
  - Restores normal monitoring screens and LED follow mode after the clear message

- **Critical Shutdown** (<12.7V default)
  - Automatic graceful system shutdown
  - Prevents data corruption

### Normal Operation
- **ARGB LED Mode**: Follow mode with cyan (0,6,6) color without constant resets
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
# Required Python packages are listed in requirements.txt
sudo apt-get install -y $(grep -Ev '^(#|$)' requirements.txt | tr '\n' ' ')
```
This installs the Python runtime libraries, including `python3-luma.core` and `python3-luma.oled`. The Python ATAK receiver uses only standard-library imports (`socket`, `threading`, and `stat`); it does not add a pip dependency. Its `api_*` imports are local modules in this repository and must remain on the Python import path.

The optional Perl ATAK producer is included in `atak_monitor.pl`; its separate system dependencies are listed in [`requirements-atak.txt`](requirements-atak.txt). Install these only when deploying that producer.

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
    "critical_voltage_threshold": 12.7,
    "battery_capacity_ah": null
  },
  "OLED": {
    "screen_durations": {
      "date_time": 7.0,
      "utilization": 15.0,
      "fans": 7.0,
      "temperatures": 7.0,
      "victron": 30.0
    }
  }
}
```
`battery_capacity_ah` is a whole number of amp-hours. Leave it `null` to read the current capacity from the shunt on startup; the configured value is then written to the shunt once each time the service starts.

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

### Optional: Install ATAK Emergency Monitoring

The Python receiver is included in `task_victron_oled.py`; the Perl producer and its systemd unit are included as `atak_monitor.pl` and `systemd/atak_monitor.service`.

The producer connects to the TAK server using mutual TLS and sends alert payloads to `/run/victron-monitor/victron_alerts.sock`. Its defaults expect the TAK server at `takserver:8089` and certificates named `admin.pem`, `admin.key`, and `ca.pem` under the configured certificate directory. Edit the producer's server hostname or address (whichever is accepted when connecting to the atak admin console) and certificate directory to match your installation. Both services run as `pi`; the Victron monitor's systemd unit creates the shared runtime directory (in memory).

Install the optional Perl modules:
```bash
cd ~/victron-fnk0107-monitor
sudo apt-get update
sudo apt-get install -y $(grep -Ev '^(#|$)' requirements-atak.txt | tr '\n' ' ')
```
The Perl producer uses `IO::Socket::SSL`, `XML::Simple`, and `Geo::Coordinates::UTM` for conversion of lat/long to MGRS.

Install the supplied producer and unit:
```bash
sudo install -m 0755 atak_monitor.pl /usr/local/bin/atak_monitor.pl
sudo install -m 0644 systemd/atak_monitor.service /etc/systemd/system/atak_monitor.service
```

The service runs as `pi`. Grant that account read access to the required certificate files and traverse access to their parent directories; keep the private key restricted to the service account/group and do not make it world-readable. Then enable ATAK monitoring:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now atak_monitor.service
sudo systemctl status atak_monitor.service
sudo journalctl -u atak_monitor.service -f
```

Start `victron-monitor.service` as described above. Confirm both services use the same account, the socket path is available at startup, and the logs show the TLS connection and a listening ATAK socket. To test, send a test emergency from ATAK and verify the OLED marquee/LED pattern; clear the emergency and verify normal rotation and follow mode resume.

## 📁 Project Structure

```
victron-fnk0107-monitor/
├── README.md                      # This file
├── TESTING.md                     # Comprehensive testing guide
├── requirements.txt               # System packages (apt)
├── requirements-atak.txt          # Optional Perl ATAK producer packages (apt)
├── atak_monitor.pl                # Optional ATAK/TAK TLS producer
├── app_config.json               # Configuration file
├── api_victron.py                # Victron shunt communication
├── api_expansion.py              # FNK0107 case control (from Freenove)
├── api_json.py                   # Configuration management
├── api_systemInfo.py             # Pi system information (from Freenove)
├── api_oled.py                   # OLED display (from Freenove)
├── task_victron_oled.py          # Main integrated task
├── task_led.py                   # LED control daemon
├── task_fan.py                   # Fan control daemon
├── task_manager.py               # Task orchestration
├── systemd/
│   ├── atak_monitor.service       # Optional ATAK producer service
│   └── victron-monitor.service   # Systemd service
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

### Screen 1: Date / Time
```
     12:34:56

    2026-09-26
```

### Screen 2: Utilization
```
 CPU  MEM  DSK
  ◯    ◯    ◯
 20%  45%  75%
```

### Screen 3: Fan Speeds
```
 F1   F2   F3
  ◯    ◯    ◯
 65%  58%  72%
```

### Screen 4: Temperatures
```
 CPU   │  CASE
 42C   │  38C
```

### Screen 5: Victron Battery
Power and current share a row with the charge-direction arrow in the center. Voltage and SOC share the next row; `Rem` is the Victron-reported remaining time.
```
 72.00W    ↑    5.40A
 13.20V   87.00%
 Rem 4h 32m
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
- Should not be a factor, resource utilization was too small to measure during testing, even on a heavily-loaded Pi 5 8gb.  however, if you are having issues, consider utizing hardware QoS to prioritize software access to CPU and memory on your Pi, rather than making changes below (out of scope here, but the author has found this extremely effective to nullify/prevent resource issues 
- if deemed necessary, Reduce polling frequency in `app_config.json`
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
`screen_durations` sets the rotation duration in seconds for each named screen. Defaults are 7 seconds for date/time, fan, and temperature screens; 15 seconds for utilization (CPU/memory/disk); and 30 seconds for Victron power. Older configurations using `system_screen_display_time`, `screen1.display_time`, or `screen2.display_time` remain supported as fallbacks.

```json
{
  "OLED": {
    "screen_durations": {
      "date_time": 7.0,
      "utilization": 15.0,
      "fans": 7.0,
      "temperatures": 7.0,
      "victron": 30.0
    }
  }
}
```

### LED Modes (defaults)
- **Normal**: Follow mode cyan (0, 6, 6)
- **Voltage Alert**: Flashing red/blue
- **Atak Emergency Alert**: Flashing red/green
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

Your contributions are welcome!

## 📚 References

- [Victron VE.Direct Protocol](https://www.victronenergy.com/live/VE.Direct_Protocol:Home)
- [Freenove FNK0107 Docs](https://docs.freenove.com/projects/fnk0107/en/latest/)
- [Raspberry Pi GPIO/I2C](https://www.raspberrypi.com/documentation/)

## ⚡ Status

## v1.1 Release Notes

- Added ATAK emergency alert reception through a local Unix-domain socket.  The OLED display will show the type of alert, the call sign of the sender, and their MGRS coordinates for all Atak Emergency alerts until they are cleared in Atak.  Although this has only been tested on Atak-Civ 5.6, it should also work on the full military version of Atak 5.6.
- Added OLED marquee and red/green ARGB LED override, returning to normal monitoring when cleared.  All LED colours and patterns for the various states are configurable in the JSON file.
- Included the Perl ATAK producer and systemd service; documented optional dependencies, mutual-TLS configuration, and certificate permissions.
- Audio alerts using the audio capabilities of the Freenove case may be added later.

**Release status:** v1.1 producer and receiver assets are included.

### Installation Quick Links
- [Installation Guide](#-installation)
- [Deployment Instructions](#-installation)
- [Troubleshooting](#-troubleshooting)

### Roadmap
- [x] v1.0 - Core Victron monitoring (released)
- [ ] v1.1 - ATAK emergency integration (hardware validation pending)
- [ ] Web dashboard
- [ ] Data logging & history
- [ ] Mobile app integration

---

**Questions?** Open an issue or check the [Wiki](https://github.com/DarkRanger935/victron-fnk0107-monitor/wiki)

**Current published version**: v1.0
**Next documented version**: v1.1
**Repository**: [DarkRanger935/victron-fnk0107-monitor](https://github.com/DarkRanger935/victron-fnk0107-monitor)
