import httpx

BASE_URL = "http://127.0.0.1:8000"

def sync_incidents():
    response = httpx.post(
        f"{BASE_URL}/incidents/sync",
        params={
            "window_seconds": 120,
            "method": "upstream_anchor_quorum_v2"
        },
        timeout=30
    )

    response.raise_for_status()
    return response.json()


def main():
    print("Starting live osTicket verification...")

    first = sync_incidents()
    print("First synchronization:", first)

    second = sync_incidents()
    print("Second synchronization:", second)

    if first.get("ticket_errors") or second.get("ticket_errors"):
        raise RuntimeError("Ticket synchronization failed")

    if first.get("ticketing") != "enabled" or second.get("ticketing") != "enabled":
        raise RuntimeError("Ticketing is not enabled")

    if second.get("tickets_created"):
        raise RuntimeError("Unexpected tickets created on repeated sync")

    print("Repeated synchronization completed without new tickets.")
    print("Verify the existing ticket in the osTicket dashboard.")


if __name__ == "__main__":
    main()