"""Address/serial defaults; main.py asks USB/AP/both at every normal Run."""

# Join this network manually for AP. This script does not change computer Wi-Fi.
# Use the Wi-Fi password supplied with the kit.
AP_SSID = "aerion drone"
AP_HOST = "192.168.4.1"
AP_PORT = 8080

# Blank lists USB ports for selection. You normally do not need to edit this.
# Mac example: "/dev/cu.usbmodem101"; Windows: "COM5".
PORT = ""
BAUDRATE = 115200

# Only when USB opens; no reset command is sent. Keep FC stationary at startup.
STARTUP_WAIT_SECONDS = 4.0
