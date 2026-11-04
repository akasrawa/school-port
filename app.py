"""Entry point for Vercel (zero-config Flask): Vercel looks for a Flask instance named `app` here."""
from server import create_app

app = create_app()
