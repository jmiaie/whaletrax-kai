#!/usr/bin/env python3
import sys
from pathlib import Path
from wsgiref.simple_server import make_server

sys.path.insert(0, str(Path(__file__).resolve().parent))
from polyshark_webhook import app, check_config, ConfigError

try:
    check_config()  # fail fast at startup with a clear message, not at import
except ConfigError as e:
    sys.exit(f'Polyshark webhook misconfigured: {e}')

print('Starting Polyshark webhook server on :8080')
httpd = make_server('', 8080, app)
print('Server ready')
httpd.serve_forever()
