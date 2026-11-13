"""Launch the importable worker through the LiveKit Agents CLI."""

from .worker import server

if __name__ == "__main__":
    from livekit.agents import cli

    cli.run_app(server)
