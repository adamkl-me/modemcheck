# ModemCheck Cloud Backup - Systemd Setup

Systemd service and timer for automated daily backups of PostgreSQL and Redis.

## Installation

**1. Copy service files to systemd directory:**
```bash
sudo cp modemcheck-cloud-backup.service /etc/systemd/system/
sudo cp modemcheck-cloud-backup.timer /etc/systemd/system/
```

**2. Reload systemd to recognize new units:**
```bash
sudo systemctl daemon-reload
```

**3. Enable and start the timer:**
```bash
# Enable timer to start on boot
sudo systemctl enable modemcheck-cloud-backup.timer

# Start timer now
sudo systemctl start modemcheck-cloud-backup.timer
```

**4. Verify timer is active:**
```bash
# Check timer status
sudo systemctl status modemcheck-cloud-backup.timer

# List all timers (shows next scheduled run)
systemctl list-timers modemcheck-cloud-backup.timer
```

## Usage

### Check Timer Status
```bash
# Show timer status and next scheduled run
systemctl status modemcheck-cloud-backup.timer

# Show all timers including next activation time
systemctl list-timers
```

### Manual Backup Trigger
```bash
# Run backup immediately (without waiting for timer)
sudo systemctl start modemcheck-cloud-backup.service

# Check backup job status
systemctl status modemcheck-cloud-backup.service
```

### View Backup Logs
```bash
# View service logs (last 50 lines)
journalctl -u modemcheck-cloud-backup.service -n 50

# Follow logs in real-time
journalctl -u modemcheck-cloud-backup.service -f

# View logs for specific date
journalctl -u modemcheck-cloud-backup.service --since "2025-11-17"

# View application logs (written by backup script)
tail -f /home/adamkl/projects/modemcheck/cloudserver/logs/backup.log
```

### Disable Backups
```bash
# Stop timer (stops automatic backups)
sudo systemctl stop modemcheck-cloud-backup.timer

# Disable timer (won't start on boot)
sudo systemctl disable modemcheck-cloud-backup.timer
```

## Schedule Configuration

**Default schedule:** Daily at 2:00 AM

**To change schedule**, edit `/etc/systemd/system/modemcheck-cloud-backup.timer`:

```ini
# Examples of OnCalendar values:

# Every day at 2 AM (current setting)
OnCalendar=*-*-* 02:00:00

# Every day at 3:30 AM
OnCalendar=*-*-* 03:30:00

# Twice daily (2 AM and 2 PM)
OnCalendar=*-*-* 02,14:00:00

# Every 12 hours
OnCalendar=*-*-* 00,12:00:00

# Weekly on Sunday at 2 AM
OnCalendar=Sun *-*-* 02:00:00

# First day of month at 2 AM
OnCalendar=*-*-01 02:00:00
```

After editing, reload and restart:
```bash
sudo systemctl daemon-reload
sudo systemctl restart modemcheck-cloud-backup.timer
```

## Features

### Persistent Backups
If system is powered off at scheduled time, backup runs 15 minutes after next boot.

### Randomized Start
5-minute random delay prevents load spikes if multiple services start simultaneously.

### Resource Limits
- CPU: Limited to 50% of one core
- Memory: Limited to 512MB
- Prevents backup from impacting production services

### Security Hardening
- Runs as user `adamkl` (not root)
- Requires `docker` group membership
- `NoNewPrivileges` prevents privilege escalation
- `PrivateTmp` isolates temporary files

## Backup Details

**What gets backed up:**
- PostgreSQL database (compressed SQL dump)
- Redis data (RDB snapshot)

**Backup location:**
- PostgreSQL: `cloudserver/backups/postgres/`
- Redis: `cloudserver/backups/redis/`

**Retention:**
- Default: 30 days
- Automatic cleanup of old backups

**Verification:**
- Gzip integrity check
- Table count validation
- Size verification

## Troubleshooting

### Timer not running
```bash
# Check if timer is enabled
systemctl is-enabled modemcheck-cloud-backup.timer

# Check if timer is active
systemctl is-active modemcheck-cloud-backup.timer

# Enable and start if needed
sudo systemctl enable --now modemcheck-cloud-backup.timer
```

### Service fails
```bash
# Check service status
systemctl status modemcheck-cloud-backup.service

# View full logs
journalctl -u modemcheck-cloud-backup.service -n 100 --no-pager

# Test backup script manually
cd /home/adamkl/projects/modemcheck/cloudserver
./backup-all.sh --verify
```

### Docker permission issues
```bash
# Verify user is in docker group
groups adamkl

# Add user to docker group if needed
sudo usermod -aG docker adamkl

# Reload groups (or logout/login)
newgrp docker
```

### Check next scheduled run
```bash
systemctl list-timers modemcheck-cloud-backup.timer
```

## Uninstallation

```bash
# Stop and disable timer
sudo systemctl stop modemcheck-cloud-backup.timer
sudo systemctl disable modemcheck-cloud-backup.timer

# Remove unit files
sudo rm /etc/systemd/system/modemcheck-cloud-backup.service
sudo rm /etc/systemd/system/modemcheck-cloud-backup.timer

# Reload systemd
sudo systemctl daemon-reload
```

## Monitoring

### Email Notifications (Optional)

Install mail utilities:
```bash
sudo apt-get install mailutils
```

Create wrapper script `/home/adamkl/projects/modemcheck/cloudserver/backup-with-notification.sh`:
```bash
#!/bin/bash
cd /home/adamkl/projects/modemcheck/cloudserver
if ./backup-all.sh --verify; then
    echo "Backup completed successfully" | mail -s "ModemCheck Backup: Success" admin@example.com
else
    echo "Backup failed! Check logs: journalctl -u modemcheck-cloud-backup.service" | \
        mail -s "ModemCheck Backup: FAILED" admin@example.com
fi
```

Update service file to use wrapper script:
```ini
ExecStart=/home/adamkl/projects/modemcheck/cloudserver/backup-with-notification.sh
```

## See Also

- Backup scripts: `cloudserver/backup-*.sh`
- Restore script: `cloudserver/restore-database.sh`
- Operations guide: `cloudserver/OPERATIONS.md`
- Cron alternative: `cloudserver/cron-example.txt`
