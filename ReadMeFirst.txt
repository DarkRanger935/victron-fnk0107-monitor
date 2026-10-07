The service is being revised to incorporate complete the following new atak_monitor network daemon to your existing victron-monitor framework.  It uses a local, non-blocking Unix Domain Socket.
This setup establishes a lightning-fast, zero-overhead pipeline. It decodes incoming ATAK packets, extracts critical incident details, and pushes them down a thread-safe pipe. The victron-monitor then overrides standard loops to trigger full-scale emergency alerts to be displayed as scrolling marquee message(s) on the OLED display, with a special ARGB Flash pattern and sound alert.
------------------
## Component 1: The New ATAK Monitor Service (atak_monitor.pl)
This Perl script runs as a standalone daemon on your Pi 5. It continuously receives ATAK traffic from the server on port 8089, handles conversions to MGRS grid strings, and directly pushes string alerts over to the Victron receiver socket path at /run/user/1000/victron_alerts.sock.

>>See attached file, atak_monitor.pl<<, which must be copied during installation over to /usr/local/bin/atak_monitor.pl

During Install, the user must make the script executable:

sudo chmod +x /usr/local/bin/atak_monitor.pl

------------------------------
## Component 2: Systemd Unit Configuration (atak_monitor.service)
The attached custom system service description is used to manage the life cycle of the new monitor network process on the Pi 5.
>>See attached file atak_monitor.service<<, during install save this configuration file as /etc/systemd/system/atak_monitor.service

Enable and start the service via systemctl:

sudo systemctl daemon-reload
sudo systemctl enable atak_monitor.service
sudo systemctl start atak_monitor.service

------------------------------
## Component 3: Integration for victron-fnk0107-monitor (task_victron_oled.py)

Copilot: weave the alarm logic directly into your python framework without blocking the critical loops polling your Victron Shunt, this script launches an independent background thread. This thread hosts the matching local Unix Domain Socket Server to listen for alerts from atak_monitor.pl.
When an alert lands, a state tracking machine intercepts the routine execution loop. It scrolls large marquee text across your SSD1306 OLED, sounds a continuous chime buzzer, and shifts your FNK0107 ARGB LED arrays to run your requested alternate flashing sequence.
Update your primary orchestration python file (task_victron_oled.py or task_manager.py) with this production structure, incorporating existing code and functions as required:

import os
import sys
import socket
import threading
import time
# --- Mocking core API dependencies based on victron-fnk0107-monitor structure ---
# In production, these resolve to your repository files (api_oled, api_expansion, etc.)
try:
    from api_oled import OledDevice  # Freenove OLED wrapped library
    from api_expansion import ExpansionBoard  # FNK0107 Case Controls
except ImportError:
    # Fallback placeholders for testing purposes
    class OledDevice:
        def __init__(self): pass
        def clear(self): pass
        def draw_text_large(self, text, x, y): pass
        def display(self): pass
    class ExpansionBoard:
        def __init__(self): pass
        def set_buzzer(self, state): pass
        def set_led_color(self, index, r, g, b): pass
# --- Active State Engine Globals ---ATAK_ALERT_ACTIVE = FalseATAK_ALERT_TEXT = ""SOCKET_PATH = "/run/user/1000/victron_alerts.sock"
def init_uds_server():
    """Initializes and runs the background UNIX Domain Socket IPC Server thread."""
    if os.path.exists(SOCKET_PATH):
        try:
            os.unlink(SOCKET_PATH)
        except OSError:
            pass

    # Ensure the target memory runtime workspace folder path exists
    os.makedirs(os.path.dirname(SOCKET_PATH), exist_ok=True)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)
    server.listen(5)
    # Grant permissions so the other systemd service can connect seamlessly
    os.chmod(SOCKET_PATH, 0o660)

    def listen_loop():
        global ATAK_ALERT_ACTIVE, ATAK_ALERT_TEXT
        print(f"[IPC] Listening for ATAK notifications on {SOCKET_PATH}...")
        while True:
            try:
                conn, _ = server.accept()
                data = conn.recv(1024).decode('utf-8').strip()
                if data:
                    print(f"[IPC] Raw data payload intercepted: {data}")
                    # Protocol fields: CLEAR_STATUS|ALERT_TYPE|CALLSIGN|MGRS
                    parts = data.split('|')
                    if len(parts) >= 4:
                        is_cleared = parts[0].lower() == 'true'
                        alert_type = parts[1]
                        callsign = parts[2]
                        mgrs_pos = parts[3]

                        if is_cleared:
                            print(f"[IPC] Received CLEAR command for {callsign}")
                            ATAK_ALERT_ACTIVE = False
                            ATAK_ALERT_TEXT = ""
                        else:
                            print(f"[IPC] CRITICAL EVENT ACTIVATED from {callsign}")
                            ATAK_ALERT_ACTIVE = True
                            # Build plain text string requested for the Marquee
                            ATAK_ALERT_TEXT = f"*** {alert_type} *** CALLSIGN: {callsign} *** MGRS: {mgrs_pos} ***   "
                conn.close()
            except Exception as e:
                print(f"[IPC] Error inside communication pipeline: {e}")
                time.sleep(1)

    t = threading.Thread(target=listen_loop, daemon=True)
    t.start()
def execute_hardware_override_alert(oled, board):
    """
    Executes a high-priority loop sequence driving physical assets.
    Alternates case lights every 300ms, ticks chimes, and rolls large marquee lines.
    """
    global ATAK_ALERT_ACTIVE, ATAK_ALERT_TEXT
    
    # Marquee state tracker tracking the string slice boundaries
    scroll_index = 0
    toggle_state = False
    last_toggle_time = time.time()

    print("[ALERT] Swapping hardware stack layers into OVERRIDE mode.")

    while ATAK_ALERT_ACTIVE:
        current_time = time.time()
        
        # 1. Handle Flash Mechanics for ARGB LEDs and System Buzzer (300ms cycle)
        if current_time - last_toggle_time >= 0.300:
            toggle_state = not toggle_state
            last_toggle_time = current_time
            
            # Sound alarm chime sync
            board.set_buzzer(1 if toggle_state else 0)
            
            # Alternating bright white (255,255,255) and bright Green (0,255,0)
            for led_id in range(4): # Matches 4 physical FNK0107 chassis strips
                if toggle_state:
                    board.set_led_color(led_id, 255, 0, 0)   # Red
                else:
                    board.set_led_color(led_id, 0, 255, 0)   # Green

        # 2. Render Text Marquee Frame Window to OLED (Large Font Display)
        oled.clear()
        # Create a wrapping substring slice to make text loop smoothly
        visible_text = ATAK_ALERT_TEXT[scroll_index:] + ATAK_ALERT_TEXT[:scroll_index]
        # Crop visible boundary space to prevent screen overflowing
        visible_frame = visible_text[:16] 
        
        # Draw text onto OLED screen using large dimensions
        oled.draw_text_large(visible_frame, x=0, y=16)
        oled.display()

        # Step forward marquee position pointer index 
        scroll_index += 1
        if scroll_index >= len(ATAK_ALERT_TEXT):
            scroll_index = 0

        # Small yield pause controlling scrolling marquee animation speed
        time.sleep(0.150)

    # Clean up and reset physical assets when alert clears
    board.set_buzzer(0)
    print("[ALERT] ATAK clear event parsed. Returning hardware control to normal monitor loop.")
def main_orchestration_loop():
    """Primary tracking wrapper integrated into the existing framework."""
    # Instantiation mappings matching your current repository configurations
    oled = OledDevice()
    board = ExpansionBoard()

    # Spin up the UDS receiver engine thread
    init_uds_server()

    print("[SYSTEM] Main monitoring services initialized successfully.")
    
    while True:
        # Check if the independent thread has logged an incoming tactical incident
        if ATAK_ALERT_ACTIVE:
            execute_hardware_override_alert(oled, board)

        # -------------------------------------------------------------
        # STANDARD POWER MONITOR LOOPS GO HERE 
        # (Your existing code reading parameters from Victron SmartShunt,
        # updating standard utilization stats, and maintaining base cyan lights)
        # -------------------------------------------------------------
        
        # Example dummy tracking placeholder for standard loop execution
        # print("Polling standard metrics...")
        time.sleep(1)
if __name__ == "__main__":
    main_orchestration_loop()


## Required Dependencies Update
Because this approach uses an encrypted SSL stream, you will need to add the OpenSSL development wrapper package to your Pi 5: [3] 

sudo apt update
sudo apt install -y libio-socket-ssl-perl

## Step-by-Step Security and Permissions Fix
Because these specific keys are located outside the normal root space, you must configure security settings to allow the Perl background process (which runs outside the container as user pi) to access them securely.

## 1. Configure File Access
By default, Docker locks down certificate files with strict root-only user permissions. If the file manager prevents the external system service from reading the keys, atak_monitor.pl will trigger a permission crash. [5] 
To solve this safely without compromising security, create a dedicated system access group, add the pi user to it, and grant group-read access to the keys:

# Create a dedicated group for TAK certificate access
sudo groupadd takcerts
# Assign your service user (pi) to the new group
sudo usermod -aG takcerts pi

# Update folder permissions to allow group access
sudo chown -R :takcerts /TAKSERVER/takserver-docker-5.6-RELEASE-57/tak/certs/files
sudo chmod 750 /TAKSERVER/takserver-docker-5.6-RELEASE-57/tak/certs/files
sudo chmod 640 /TAKSERVER/takserver-docker-5.6-RELEASE-57/tak/certs/files/*

# Apply group changes to the current terminal session
newgrp takcerts

## 2. Update and Restart the Service

sudo systemctl restart atak_monitor.service

# FYI, You can view the active log feed directly to confirm the mTLS handshake completes successfully with the Docker engine: [1] 

journalctl -u atak_monitor.service -f -n 20

