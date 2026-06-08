from uvicorn import run

from backend.app.core.config import get_settings


def main() -> None:
    settings = get_settings()
    run(
        "backend.app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        factory=False,
    )


if __name__ == "__main__":
    main()
