#!/bin/bash

# Fix permissions on mounted volumes (needed because volumes override Dockerfile permissions)
chown -R nginx:nginx /modemcheck-cloud/datafiles
chown -R nginx:nginx /modemcheck-cloud/config
chmod -R 755 /modemcheck-cloud/datafiles
chmod -R 755 /modemcheck-cloud/config

# Start fcgiwrap
spawn-fcgi -s /run/fcgiwrap/fcgiwrap.sock -U nginx -u nginx -- /usr/bin/fcgiwrap &

# Start nginx in foreground
nginx -g 'daemon off;'
