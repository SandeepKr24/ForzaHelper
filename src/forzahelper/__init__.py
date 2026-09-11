"""ForzaHelper backend package."""

__all__ = ["main"]


def main() -> None:
    """Run the API server. Entry point for `uv run forzahelper`."""
    import uvicorn

    from .config import get_settings

    settings = get_settings()
    uvicorn.run(
        "forzahelper.api:app",
        host="127.0.0.1",
        port=8000,
        reload=settings.environment == "development",
    )
