#!/usr/bin/env python3
from wsgiref.simple_server import make_server
import sys
sys.path.insert(0, '/home/ubuntu/.openclaw/workspace/repos/whaletrax')
from polyshark_webhook import app

print('Starting Polyshark webhook server on :8080')
httpd = make_server('', 8080, app)
print('Server ready')
httpd.serve_forever()