#!/bin/bash

# Fix permissions on mounted volumes (needed because volumes override Dockerfile permissions)
chown -R nginx:nginx /modemcheck-cloud/config
chown -R nginx:nginx /modemcheck-cloud/data
chmod -R 755 /modemcheck-cloud/config
chmod -R 755 /modemcheck-cloud/data

# Initialize database
echo "Initializing database..."
python3 /modemcheck-cloud/cgi-bin/db_schema.py

# Start fcgiwrap
spawn-fcgi -s /run/fcgiwrap/fcgiwrap.sock -U nginx -u nginx -- /usr/bin/fcgiwrap &

# Start nginx in foreground
nginx -g 'daemon off;'
