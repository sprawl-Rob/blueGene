"""TLS trust shared by public-search and AI transports. Never disable verification."""
import ssl
from pathlib import Path

def tls_context():
    context = ssl.create_default_context()
    # python.org macOS installs may lack their optional certifi symlink.
    # Use the operating system's public CA bundle if Python has no roots loaded.
    if not context.get_ca_certs() and Path('/etc/ssl/cert.pem').is_file():
        context.load_verify_locations('/etc/ssl/cert.pem')
    return context
