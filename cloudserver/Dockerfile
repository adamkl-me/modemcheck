FROM alpine:3.22

# Install required packages
RUN apk add --no-cache \
    nginx \
    python3 \
    fcgiwrap \
    spawn-fcgi \
    bash \
    tzdata \
    sqlite

# Set timezone to America/Toronto
RUN cp /usr/share/zoneinfo/America/Toronto /etc/localtime && \
    echo "America/Toronto" > /etc/timezone

# Create directory structure
RUN mkdir -p /modemcheck-cloud/cgi-bin && \
    mkdir -p /modemcheck-cloud/config && \
    mkdir -p /modemcheck-cloud/data && \
    mkdir -p /run/fcgiwrap && \
    mkdir -p /var/log/nginx

# Set up permissions - make config and data writable by nginx user
RUN chmod 755 /modemcheck-cloud && \
    chmod 777 /modemcheck-cloud/config && \
    chmod 777 /modemcheck-cloud/data && \
    chmod 755 /modemcheck-cloud/cgi-bin && \
    chown -R nginx:nginx /modemcheck-cloud/config && \
    chown -R nginx:nginx /modemcheck-cloud/data

# Copy application files
COPY db-viewer.html /modemcheck-cloud/index.html
COPY db-viewer.js /modemcheck-cloud/
COPY admin.html /modemcheck-cloud/
COPY admin-login.html /modemcheck-cloud/
COPY login.html /modemcheck-cloud/
COPY cgi-bin/db-api.py /modemcheck-cloud/cgi-bin/
COPY cgi-bin/db_schema.py /modemcheck-cloud/cgi-bin/
COPY cgi-bin/audit_schema.py /modemcheck-cloud/cgi-bin/
COPY cgi-bin/upload.py /modemcheck-cloud/cgi-bin/
COPY cgi-bin/admin-api.py /modemcheck-cloud/cgi-bin/
COPY cgi-bin/auth.py /modemcheck-cloud/cgi-bin/
COPY cgi-bin/user-management.py /modemcheck-cloud/cgi-bin/
COPY nginx.conf /etc/nginx/http.d/modemcheck.conf

# Remove default nginx config that listens on port 80
RUN rm -f /etc/nginx/http.d/default.conf

# Make CGI scripts executable
RUN chmod +x /modemcheck-cloud/cgi-bin/db-api.py && \
    chmod +x /modemcheck-cloud/cgi-bin/upload.py && \
    chmod +x /modemcheck-cloud/cgi-bin/admin-api.py && \
    chmod +x /modemcheck-cloud/cgi-bin/auth.py && \
    chmod +x /modemcheck-cloud/cgi-bin/user-management.py

# Create startup script
COPY start.sh /start.sh
RUN chmod +x /start.sh

# Expose ports: 22557 (API), 23890 (Viewer), 23891 (Admin)
EXPOSE 22557 23890 23891

# Start services
CMD ["/start.sh"]
