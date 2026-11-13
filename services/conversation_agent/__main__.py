"""Run the explicit native scripted-conversation agent profile."""

from livekit.agents import cli

from .telemetry import configure_logging
from .worker import server


def main() -> None:
    configure_logging()
    cli.run_app(server)


if __name__ == "__main__":
    main()
