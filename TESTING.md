# v0.1.0 Testing Instructions

## ⚠️ IMPORTANT: Testing Phase

Thank you for being part of the v0.1.0 validation phase! This release needs real-world hardware testing on your Raspberry Pi 5 + FNK0107 case + Victron shunt setup.

## Prerequisites

### Hardware Setup
1. **Raspberry Pi 5** (64-bit Bookworm OS installed)
2. **Freenove FNK0107 Computer Case Kit Pro** (fully assembled)
3. **Victron 300A SmartShunt Monitor** (wired to battery system)
4. **VE.Direct to USB cable** (connected to Raspberry Pi USB port)
5. **Battery power system** (or use bench supply to simulate voltages)

### Software Setup
```bash
# 1. Ensure I2C is enabled
sudo raspi-config
# Navigate to: Interface Options → I2C → Enable

# 2. Verify I2C devices detected
sudo i2cdetect -y 1
# Should show: 0x3c (OLED) and 0x21 (FNK0107 expansion board)

# 3. Verify VE.Direct USB connection
ls -la /dev/ttyUSB*
# Should show at least one device (e.g., /dev/ttyUSB0)
```

## Installation

```bash
# Clone repository
cd ~
git clone https://github.com/DarkRanger935/victron-fnk0107-monitor.git
cd victron-fnk0107-monitor

# Install system dependencies
sudo apt-get update
xargs -a requirements.txt sudo apt-get install -y
```

## Testing Phases

### Phase 1: Component Verification (15 min)

**Goal**: Confirm each hardware component is detected and responding.

```bash
# Test 1.1: Victron Connection
python3 -c "
from api_victron import VictronMonitor
m = VictronMonitor(port='/dev/ttyUSB0')
m.connect()
if m.serial_conn and m.serial_conn.is_open:
    print('✓ Victron connected')
    m.serial_conn.close()
else:
    print('✗ Victron NOT connected')
"

# Test 1.2: OLED Display
python3 -c "
from api_oled import OLED
oled = OLED(rotate_angle=180)
oled.clear()
oled.draw_text('OLED Test', position=((0,0),(128,64)), directory='center', offset=(0,28), font_size=16)
oled.show()
print('✓ OLED displaying test message for 3 seconds...')
import time
time.sleep(3)
oled.clear()
oled.show()
oled.close()
"

# Test 1.3: FNK0107 Expansion Board
python3 -c "
from api_expansion import Expansion
e = Expansion()
print(f'Board Type: {e.get_board_type()}')
print(f'Version: {e.get_version()}')
print(f'LED Mode: {e.get_led_mode()}')
print(f'Temperature: {e.get_temp()}°C')
print(f'Fan Duty: {e.get_fan_duty()}')
e.end()
print('✓ Expansion board responding')
"

# Test 1.4: System Information
python3 -c "
from api_systemInfo import SystemInformation
sys = SystemInformation()
print(f'CPU Usage: {sys.get_raspberry_pi_cpu_usage()}%')
print(f'Memory: {sys.get_raspberry_pi_memory_usage()[0]}%')
print(f'Disk: {sys.get_raspberry_pi_disk_usage()[0]}%')
print(f'CPU Temp: {sys.get_raspberry_pi_cpu_temperature()}°C')
print('✓ System information working')
"
```

**Expected Results:**
- ✓ Victron connected to /dev/ttyUSB0
- ✓ OLED displays "OLED Test" message
- ✓ FNK0107 board type detected (FNK0107 or FNK0100)
- ✓ All sensor readings show reasonable values

### Phase 2: Manual Task Execution (30 min)

**Goal**: Run the main task manually and verify display updates and LED behavior.

```bash
# Start the main task
python3 task_victron_oled.py
```

**Expected Behavior:**
- OLED Screen 1 (System Stats) - displays for ~35 seconds:
  - Date and time at top
  - CPU, Memory, Disk usage as pie charts
  - Temperature readings
  - Fan speeds
  - Alternates with Screen 2

- OLED Screen 2 (Victron Stats) - displays for ~35 seconds:
  - Voltage (V)
  - Current with direction (A ↓ charging / A ↑ discharging)
  - State of Charge (%)
  - Estimated runtime

- LED Behavior (Normal):
  - Case ARGB LEDs set to cyan (0, 6, 6) in follow mode

**Test the Low Voltage Alert:**

To simulate low voltage without disrupting your actual battery:

1. Edit `app_config.json` temporarily:
   ```json
   {
     "Victron": {
       "low_voltage_threshold": 13.5,
       "critical_voltage_threshold": 13.4
     }
   }
   ```

2. Run the task again

3. When voltage is between 13.4V and 13.5V:
   - OLED displays low voltage alert overlay:
     - "⚠️ LOW VOLTAGE"
     - Actual voltage reading
     - "Shutdown Imminent!"
   - ARGB LEDs flash red (255,0,0) and blue (0,0,255) alternating every 1 second

4. Restore original thresholds in `app_config.json`:
   ```json
   {
     "Victron": {
       "low_voltage_threshold": 12.8,
       "critical_voltage_threshold": 12.7
     }
   }
   ```

**Test Critical Shutdown (⚠️ DO NOT TEST - SKIP):**
- Voltage < 12.7V would trigger automatic system shutdown
- Skip this test to avoid unexpected shutdown
- Confirm shutdown logic in code review instead

### Phase 3: Service Installation (15 min)

**Goal**: Install as systemd service and verify auto-startup.

```bash
# Install service file
sudo cp systemd/victron-monitor.service /etc/systemd/system/

# Reload systemd daemon
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable victron-monitor.service

# Start the service
sudo systemctl start victron-monitor.service

# Check service status
sudo systemctl status victron-monitor.service

# View live logs
sudo journalctl -u victron-monitor.service -f

# Stop the service
sudo systemctl stop victron-monitor.service
```

**Expected Results:**
- Service starts successfully
- Logs show Victron, OLED, and Expansion board initialization
- OLED begins displaying alternating screens
- LEDs set to cyan (0,6,6)

### Phase 4: Stress Testing (30 min)

**Goal**: Verify stability under various conditions.

```bash
# Test 4.1: Long-running stability (30+ minutes)
# Start service and monitor for errors
sudo systemctl start victron-monitor.service
sudo journalctl -u victron-monitor.service -f
# Let run for 30+ minutes, watching logs for:
#   - No repeated error messages
#   - Consistent data updates
#   - No thread hangs

# Test 4.2: High CPU load (while service running)
stress-ng --cpu 4 --timeout 300s &
# Check OLED still updates and LEDs remain responsive

# Test 4.3: Stop/Restart cycle
for i in {1..5}; do
  sudo systemctl restart victron-monitor.service
  sleep 5
  sudo systemctl status victron-monitor.service
done
# Verify service restarts cleanly each time
```

## Reporting Test Results

Please create a GitHub issue with the following:

### Test Report Template

```markdown
## v0.1.0 Test Report

**Hardware:**
- [ ] Raspberry Pi 5 (64-bit Bookworm)
- [ ] Freenove FNK0107 Case
- [ ] Victron 300A SmartShunt
- [ ] VE.Direct USB connection
- [ ] Battery voltage range tested: ___V to ___V

**Phase 1: Component Verification**
- [ ] Victron detected and communicating
- [ ] OLED display working
- [ ] FNK0107 board detected
- [ ] System sensors reporting

**Phase 2: Manual Task Execution**
- [ ] Screen 1 (System Stats) displaying correctly
- [ ] Screen 2 (Victron Stats) displaying correctly
- [ ] Screens alternate properly every ~35 seconds
- [ ] LEDs cyan (0,6,6) in normal mode
- [ ] Low voltage alert triggered at correct threshold
- [ ] Alert LED flash (red/blue) working
- [ ] Alert message "Shutdown Imminent!" displays

**Phase 3: Service Installation**
- [ ] Service installs without errors
- [ ] Service starts successfully
- [ ] Service auto-starts on reboot
- [ ] Logs show no errors

**Phase 4: Stress Testing**
- [ ] Stable operation for 30+ minutes
- [ ] No crashes or hangs observed
- [ ] Handles high CPU load gracefully
- [ ] Restarts cleanly multiple times

**Issues/Bugs Found:**
1. [Describe any issues]
2. [Include error messages and logs]
3. [Steps to reproduce]

**Suggestions/Improvements:**
- [Any feature requests or improvements]

**Overall Assessment:**
- [ ] Ready for v0.2.0 development
- [ ] Needs bug fixes (describe below)
- [ ] Missing features (describe below)
```

## Troubleshooting

### Issue: Victron not connecting
```bash
# Check USB device
lsusb | grep -i victron

# Check serial port permissions
ls -la /dev/ttyUSB*
sudo usermod -a -G dialout pi

# Test serial connection directly
cu -l /dev/ttyUSB0 -s 19200
# Type Ctrl+D to exit
```

### Issue: OLED blank/not responding
```bash
# Verify I2C device
sudo i2cdetect -y 1
# Should show 0x3c

# Test I2C connection
sudo i2cget -y 1 0x3c 0x00
```

### Issue: Service won't start
```bash
# Check syntax
sudo systemctl status victron-monitor.service

# Check permissions
ls -la /etc/systemd/system/victron-monitor.service

# View detailed logs
sudo journalctl -u victron-monitor.service -n 50
```

### Issue: High CPU usage
- Reduce polling frequency in `app_config.json`
- Increase sleep intervals in `task_victron_oled.py`
- Check for OLED drawing bottlenecks

## Next Steps

Once testing is complete and all issues are resolved:

1. Create a GitHub issue with test report
2. Push any bug fixes as commits
3. Once validated, v0.2.0 development begins

## Support

- **Issues**: [GitHub Issues](https://github.com/DarkRanger935/victron-fnk0107-monitor/issues)
- **Documentation**: Check README.md and inline code comments
- **Hardware Help**: Refer to Freenove and Victron documentation

---

**Thank you for testing v0.1.0! Your feedback is critical to making this project production-ready.** 🎉
