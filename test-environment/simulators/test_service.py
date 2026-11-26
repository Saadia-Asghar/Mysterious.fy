"""Lab test service: a safe remediation target for M11/M12 demos.

Run:  python -m uvicorn test_service:app --app-dir test-environment/simulators --port 9100
Then register a device with device_type `test_service` and management_address
`http://127.0.0.1:9100`. Zabbix can monitor GET /health (200 healthy, 503 unhealthy).

Fault controls (lab use only):
  POST /fault/break   -> unhealthy until restarted
  POST /fault/stuck   -> unhealthy, and restart does NOT fix it (failed-recovery scenario)
  POST /fault/clear   -> healthy, no fault
"""
from fastapi import FastAPI, Response


class ServiceState:
    def __init__(self) -> None:
        self.healthy = True
        self.stuck = False
        self.restarts = 0

    def restart(self) -> None:
        self.restarts += 1
        if not self.stuck:
            self.healthy = True


def create_app(state: ServiceState | None = None) -> FastAPI:
    state = state or ServiceState()
    app = FastAPI(title="NMS lab test service")
    app.state.service = state

    @app.get("/health")
    def health(response: Response) -> dict:
        response.status_code = 200 if state.healthy else 503
        return {"healthy": state.healthy, "restarts": state.restarts}

    @app.post("/restart")
    def restart() -> dict:
        state.restart()
        return {"restarted": True, "restarts": state.restarts}

    @app.post("/fault/break")
    def fault_break() -> dict:
        state.healthy, state.stuck = False, False
        return {"healthy": False}

    @app.post("/fault/stuck")
    def fault_stuck() -> dict:
        state.healthy, state.stuck = False, True
        return {"healthy": False, "stuck": True}

    @app.post("/fault/clear")
    def fault_clear() -> dict:
        state.healthy, state.stuck = True, False
        return {"healthy": True}

    return app


app = create_app()
