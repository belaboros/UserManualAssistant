# Thermostat settings and troubleshooting

This guide covers connectivity, firmware, resetting and error codes for the Nimbus Thermostat. For installation and daily use, see the getting started guide.

## Wi-Fi

The thermostat connects to a 2.4 GHz Wi-Fi network. It cannot use 5 GHz-only networks.

1. Press the dial and choose **Menu > Settings > Connect > Wi-Fi**.
2. Select your network from the list. Turn the dial to move through letters when you enter the password, and press the dial to confirm each one.
3. Wait for the Wi-Fi symbol in the top corner of the display to stop blinking. A solid symbol means the thermostat is online.

If you change your router or Wi-Fi password, repeat these steps. The thermostat keeps its schedules and settings when the Wi-Fi network changes.

## Connect to a hub

The thermostat can talk to a Nimbus Hub over the Nimbus mesh radio. A hub lets you control the thermostat from the Nimbus app and from other Nimbus devices, even when your Wi-Fi is unreliable.

Put the hub into pairing mode first, as described in the hub guide. Then, on the thermostat:

1. Press the dial and choose **Menu > Settings > Connect > Hub**.
2. The display shows "Searching for hub". Keep the thermostat within 5 meters of the hub during pairing.
3. When the hub is found, the display shows a 6-digit code. Keep this screen open and finish pairing in the Nimbus app, where you confirm the code.
4. When pairing succeeds, the display shows the hub name and a check mark.

If the thermostat does not find the hub within two minutes, it shows error E4. See the error codes section.

## Firmware updates

The thermostat checks for new firmware once a day when it is online. When an update is available, the display shows an update symbol.

To install an update immediately, choose **Menu > Settings > Firmware > Update now**. The update takes about five minutes. The display goes dark and restarts during this time. Do not switch off the power during an update. Your heating and cooling keep running with the last settings.

To see the installed firmware version, choose **Menu > Settings > Firmware > Version**.

You can turn off automatic updates under **Menu > Settings > Firmware > Auto update**. We recommend leaving them on.

## Factory reset

A factory reset erases all schedules, the Wi-Fi password and the hub pairing. The installation and system type settings are kept. Use a factory reset when you give the thermostat to someone else or when other troubleshooting steps do not help.

1. Remove the display unit from the wall plate.
2. Find the small reset pin hole on the back of the display unit.
3. Insert a straightened paper clip into the hole and hold the reset pin for 10 seconds. Do not release it before the display shows the Nimbus logo.
4. Release the pin and put the display unit back on the wall plate.
5. The thermostat restarts and shows the setup assistant.

Remember to remove the thermostat from the Nimbus app after a factory reset so the old entry does not remain in your device list.

## Error codes

The display shows an error code when the thermostat finds a problem. The codes are listed below.

### E1: Temperature sensor fault

The internal temperature sensor gives readings that are out of range. Switch the power off at the circuit breaker for 30 seconds and switch it on again. If the code returns, the sensor is defective and the unit needs service.

### E2: Wi-Fi connection lost

The thermostat cannot reach your Wi-Fi network. Check that your router is on and in range. Then reconnect under **Menu > Settings > Connect > Wi-Fi**. Schedules keep running while E2 is shown.

### E3: Heating or cooling system not responding

The thermostat sends a call for heat or cooling, but the system does not respond. Check that the circuit breaker for the system is on and that the system's own safety switch is closed. Check the wiring at the terminals, especially R and W for heating and R and Y for cooling. If the wiring is correct and E3 stays on the display, contact a qualified heating technician. E3 does not mean that the thermostat is defective.

### E4: Hub not found

The thermostat could not find a hub while pairing, or it lost the link to a paired hub for more than ten minutes. Make sure the hub is powered on and within range, and that it is in pairing mode if you are pairing for the first time. Then try again under **Menu > Settings > Connect > Hub**.
