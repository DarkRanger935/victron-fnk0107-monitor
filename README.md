# victron-fnk0107-monitor

Raspberry Pi 5 power monitoring system integrating a Victron shunt monitor with FNK0107 case control, OLED display, and ARGB LEDs with low-voltage alert.

## Alert overlay

When the Victron voltage is at or below 12.8 V, the OLED displays a low-voltage alert. The final line is:

> Shutdown Imminent!

The display implementation should horizontally scroll this line when it does not fit on the OLED.

The critical shutdown threshold is 12.7 V.

## Release status

The first release is not yet built. This repository currently contains the project README only; the Freenove source and Victron integration still need to be added and tested on the target Raspberry Pi hardware.

## Notifications

This service cannot send email notifications. When a release is actually published, notification can be configured through GitHub repository **Watch** settings or a GitHub Actions/webhook integration.
