#!/bin/bash

# Fix permissions on mounted volumes (needed because volumes override Dockerfile permissions)
chown -R nginx:nginx /modemcheck-cloud/config
chown -R nginx:nginx /modemcheck-cloud/data
chmod -R 755 /modemcheck-cloud/config
chmod -R 755 /modemcheck-cloud/data

# Initialize databases
echo "Initializing databases..."
python3 /modemcheck-cloud/cgi-bin/db_schema.py
python3 /modemcheck-cloud/cgi-bin/audit_schema.py

# Start fcgiwrap with process pool (10 workers for concurrent request handling)
spawn-fcgi -s /run/fcgiwrap/fcgiwrap.sock -U nginx -u nginx -F 10 -- /usr/bin/fcgiwrap &

# Start nginx in foreground
nginx -g 'daemon off;'
