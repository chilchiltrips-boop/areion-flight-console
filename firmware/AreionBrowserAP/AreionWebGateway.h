#pragma once
#include <IPAddress.h>

// Called once after the existing kit UDP transport is ready. HTTP and socket
// work run in the Espressif HTTP server task, outside the flight loop.
bool areion_web_gateway_begin(IPAddress ap, uint16_t udpPort);
