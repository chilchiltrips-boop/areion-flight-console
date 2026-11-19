# Areion FC A1 fixed connections

The board's output, PPM input and IMU bus assignments are fixed. The setup wizard shows this connection reference and does not provide pin editing.

| Function | Board signal pin | GPIO |
| --- | --- | --- |
| OUT1 / ESC1 / M1 | D0 | 0 |
| OUT2 / ESC2 / M2 | D1 | 1 |
| OUT3 / ESC3 / M3 | D2 | 2 |
| OUT4 / ESC4 / M4 | D3 | 21 |
| IMU SDA | D4 | 22 |
| IMU SCL | D5 | 23 |
| PPM receiver signal | D10 | 18 |

The connection page traces all four outputs plus the PPM receiver and IMU SDA/SCL routes. Focus controls highlight an output, PPM or IMU path. Connector positions in the drawing are schematic; the labels establish the fixed signal mapping, not power-pin polarity or exact physical pad locations. Use the board markings and verified schematic for power wiring and common signal ground.

## Quad X motor reference

Viewed from above with FRONT forward:

| Signal route | Motor location | Rotation |
| --- | --- | --- |
| OUT1 → ESC1 → M1 | Front left | CW |
| OUT2 → ESC2 → M2 | Front right | CCW |
| OUT3 → ESC3 → M3 | Back right | CW |
| OUT4 → ESC4 → M4 | Back left | CCW |

Quad X is the supported frame. Quad +, Quad H and other frame mixers are not available in this setup flow. The aircraft-profile pictures do not change the motor ordering or mixer.

## Fixed ESC output settings

All illustrated ESC profiles retain the current compiled output setup: 250 Hz, 12-bit resolution, 1000–2000 µs and duty limits 1024–2048. The profile page hides these implementation fields. Choosing Standard 50 Hz or OneShot does not program a different waveform or enable a new protocol.

## Physical calibration and motor checks

Use matching firmware, Arduino library and Python release 3.1.0. A kit without a valid completion record is ARM locked; opening setup re-locks a previously completed kit while retaining its saved settings and valid checks. Neither closing the wizard nor rebooting unlocks it. Only verified final setup completion enables a future explicit ARM request.

Endpoint calibration is scheduled explicitly for one next startup. It does not run at every startup. After scheduling, disconnect both USB and LiPo and follow the ESC maker's compatible PWM endpoint-calibration power-up procedure. The dedicated calibration boot consumes the request before its first maximum PWM output, uses three seconds high and three seconds low, then minimum. After that sequence, the FC automatically performs stationary IMU startup in the same boot while outputs stay at minimum. Keep the kit still, reconnect and verify fresh sensor status plus the ESC's actual response before testing motors. No second power cycle is required. A reset during calibration does not automatically retry it. A completed signal sequence is not proof that every ESC learned its endpoints; some models do not require calibration.

Keep all propellers removed throughout setup. The motor page requires a connected LiPo and wiring/polarity confirmation. Its independent bench API tests one or all motors at 1000–1500 µs while flight ARM stays locked. Every session starts at minimum and stops after 30 seconds or if command refresh is absent for 350 ms. Check physical motor position, rotation and reliable starting output; the on-screen animation represents a command, not measured RPM. Save and confirm each motor's result before finalizing setup.

## 2D assets

The requested board representation is a native 2D signal connection drawing. The hardware 3D viewer, tessellated mesh, original STEP package copy and mesh builder are not included in this release. No CAD dependency is required to run the GUI.

The supplied mechanical reference informed the board envelope; a mechanical model does not prove electrical nets or power polarity. The application does not infer those details from geometry. ESC, drone-profile and calibration-position drawings are scalable native vector illustrations.
