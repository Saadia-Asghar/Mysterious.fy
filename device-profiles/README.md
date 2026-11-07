# Device profiles

Reusable monitoring configuration for a device class. The integration service loads every JSON file in this directory. Camera behavior for version 1 lives in `ip_camera_basic.json` and is not copied into the service code.

A device record references `profile_id`. Its `device_type` must match the profile. Event types and metric names are accepted only when that profile declares them.
