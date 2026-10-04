# Nimbus Hub

The Nimbus Hub connects your Nimbus devices to each other and to the Nimbus app. It creates a low-power mesh network that keeps working when your internet connection is down. This guide explains setup, pairing, network options, firmware and resetting.

## What is in the box

- Nimbus Hub
- USB-C power cable and power adapter
- Ethernet cable (1 m)
- Quick start card

## Setup

1. Place the hub in a central spot, away from metal objects and microwave ovens. Keep it at least 1 meter from your Wi-Fi router.
2. Connect the power adapter. The LED glows white while the hub starts, which takes about 60 seconds.
3. Connect the Ethernet cable from the hub to your router, or set up Wi-Fi later in the Nimbus app.
4. When the LED glows solid green, the hub is online and ready for the app.

### LED status

| LED | Meaning |
| --- | --- |
| White, solid | Starting up |
| Green, solid | Online and ready |
| Blue, blinking | Pairing mode |
| Amber, blinking | No internet connection |
| Red, solid | Hardware fault |
| Purple, blinking | Installing firmware |


## Pairing devices

Use pairing mode to add a Nimbus device to the hub.

1. Press and hold the Link button on top of the hub for 3 seconds. The LED blinks blue. The hub stays in pairing mode for two minutes.
2. Start pairing on the device, then confirm the pairing in the Nimbus app. See the manuals of the device and the app for those steps.
3. When the LED returns to solid green, the device is paired.

A hub can pair with up to 50 devices. To pair a second device, press the Link button again.

If the LED stops blinking before the device connects, pairing mode has timed out. Press and hold the Link button again to restart it.

## Network

### Wi-Fi

The hub uses Ethernet by default. To use Wi-Fi instead, open the Nimbus app, select the hub and choose Hub settings > Network > Wi-Fi. The hub supports 2.4 GHz and 5 GHz networks. Disconnect the Ethernet cable after Wi-Fi shows as connected.

### IP address

By default the hub receives its address from your router through DHCP. You can set a fixed address under Hub settings > Network > IP address. Use a fixed address only if you know your network's address range.

### Mesh range

Each Nimbus device that is connected to mains power repeats the mesh signal. Battery devices do not repeat it. In an average home one hub covers about 100 square meters. Add a mains-powered device between the hub and a far-away device to extend the range.

### Reset

A network reset removes the hub's Wi-Fi settings and fixed IP address. Paired devices and the hub's name are kept.

1. In the Nimbus app, select the hub.
2. Choose Hub settings > Network > Reset network.
3. Confirm. The hub restarts and the LED glows white, then green when it is online again over Ethernet.

If you cannot reach the hub in the app, hold the Link button for 10 seconds. This also resets the network settings and does not remove paired devices.

## Hardware

### Buttons and ports

- **Link button** on top of the hub: starts pairing mode and, held for 10 seconds, resets the network settings.
- **Reset button** on the bottom, recessed: restores factory state.
- **Ethernet port** on the back: connects the hub to your router.
- **USB-C port** on the back: power input only. It does not carry data.
- **Status LED** on the front: shows the state of the hub, see the LED status table.

### Firmware

The hub installs firmware updates automatically at night between 02:00 and 04:00. The LED blinks purple during the installation. Do not disconnect the power. To update at a different time, open the app and choose Hub settings > Firmware > Update now.

### Reset

A hardware reset returns the hub to its factory state. It removes all paired devices, the Wi-Fi settings and the hub's name. Use it when you give the hub to someone else.

1. Disconnect the power adapter.
2. Press and hold the Reset button on the bottom of the hub with a paper clip.
3. Reconnect the power while you hold the button, and keep holding for 10 seconds, until the LED blinks red.
4. Release the button. The hub restarts and the LED glows white, then green.

After a hardware reset you must pair all devices again.

## Specifications

| Item | Value |
| --- | --- |
| Power | 5 V DC, USB-C, 1 A |
| Network | Ethernet 10/100, Wi-Fi 2.4 and 5 GHz |
| Mesh radio | 868 MHz |
| Bluetooth | Bluetooth LE, used by the app for setup |
| Maximum devices | 50 |
| Operating temperature | 0 C to 40 C |
