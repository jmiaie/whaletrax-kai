#!/usr/bin/env python3
import sys
sys.path.insert(0, '/home/ubuntu/.openclaw/workspace/repos/whaletrax')

# Test the webhook app
from io import BytesIO
from polyshark_webhook import app

def start_response(status, headers):
    print('Status:', status)

# Test health
environ = {'REQUEST_METHOD': 'GET', 'PATH_INFO': '/health', 'CONTENT_LENGTH': '0', 'wsgi.input': BytesIO()}
buf = BytesIO()
app(environ, start_response)
print('Health check body:', buf.getvalue())
print('TEST COMPLETE')