"""
Entrypoint CLI for Fleet API container.
Reads PORT and HOST from environment (defaulting to 0.0.0.0:8000), fully compatible with
Google Cloud Run dynamic $PORT assignment and local container runtimes.
"""
import os
import uvicorn


def main():
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run(
        "fleet_api.main:app",
        host=host,
        port=port,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
