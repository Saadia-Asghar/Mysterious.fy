# Simulators

Simulated endpoints standing in for devices when real authorized hardware isn't available.

- `test_service.py`: lab service with `/health`, `/restart` and fault controls (`/fault/break`, `/fault/stuck`, `/fault/clear`). Target of the `restart_test_service` playbook (M11) and of verification tests (M12). See the file header for how to run it.
