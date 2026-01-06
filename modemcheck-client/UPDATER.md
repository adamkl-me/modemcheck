# Automatic Updater System

The ModemCheck client includes a secure automatic update system with cryptographic signature verification and support for multiple update channels.

## Features

### Security
- **Cryptographic Signature Verification**: All updates are verified using Minisign (Ed25519) before installation
- **Pre-execution Testing**: Downloaded binaries are tested before replacing the current version
- **Automatic Rollback**: If an update fails, the system automatically restores the previous version
- **Atomic Installation**: Updates use atomic file operations to prevent corruption during installation
- **TOCTOU Protection**: Download → Verify → Test → Install workflow prevents time-of-check-time-of-use attacks

### Update Channels
- **stable** (default): Official releases only
- **beta**: Pre-release builds for testing new features
- **test**: Experimental builds for early testing

### Platform Detection
- Uses Go's `runtime.GOOS` and `runtime.GOARCH` directly
- No brittle string parsing or manual platform mapping
- Supports all platforms Go can compile for:
  - Linux (x64, ARM, ARM64, MIPS, etc.)
  - macOS/Darwin (x64, ARM64)
  - Windows (x64, x86, ARM64)
  - FreeBSD, OpenBSD, NetBSD

## Configuration

### Enable/Disable Automatic Updates

In your `config.json`:

```json
{
  "AutoUpdateEnabled": true,
  "UpdateChannel": "stable"
}
```

**Options:**
- `AutoUpdateEnabled`: `true` or `false` (default: `true`)
- `UpdateChannel`: `"stable"`, `"beta"`, or `"test"` (default: `"stable"`)

### Update Channels

**Stable (Recommended for Production)**
```json
{
  "UpdateChannel": "stable"
}
```
- Only receives official releases
- Thoroughly tested
- Recommended for production deployments
- Example versions: `v5.7.0`, `v5.7.1`, `v6.0.0`

**Beta (Early Access)**
```json
{
  "UpdateChannel": "beta"
}
```
- Receives pre-release builds marked as "beta"
- New features before stable release
- May have minor bugs
- Good for testing in non-critical environments
- Example versions: `v5.8.0-beta.1`, `v6.0.0-beta.2`

**Test (Bleeding Edge)**
```json
{
  "UpdateChannel": "test"
}
```
- Receives all pre-release builds including experimental
- Latest features and fixes
- May be unstable
- Only for development/testing
- Example versions: `v5.8.0-alpha.1`, `v5.8.0-rc.1`

## How It Works

### Update Check Process

1. **Channel Selection**: System checks your configured `UpdateChannel`
2. **GitHub API Query**:
   - Stable: Queries `/releases/latest` endpoint
   - Beta/Test: Queries `/releases` endpoint and filters for pre-releases
3. **Version Comparison**: Compares latest available with current version
4. **Platform Matching**: Finds binary for your OS/architecture
5. **Download**: If update available, downloads binary + signature
6. **Verification**: Verifies cryptographic signature
7. **Testing**: Executes binary with `--version` flag
8. **Installation**: Backs up current binary and installs new one
9. **Restart**: Restarts with new version

### Signature Verification

All releases must be signed with Minisign:

```bash
# Developer signs releases
minisign -Sm modem-check-linux-x64

# Client verifies on download
# Public key embedded in binary
# Signature downloaded alongside binary
```

If signature verification fails, the update is rejected and the download is deleted.

### Rollback Protection

The system includes multiple rollback mechanisms:

**Automatic Rollback During Installation:**
- If installation fails, previous version is automatically restored
- Update lock prevents repeated failed attempts
- 5-minute cooldown period after failed updates

**Manual Rollback:**
- Previous version saved as `modem-check.old`
- Can manually restore if needed:
  ```bash
  mv modem-check modem-check.broken
  mv modem-check.old modem-check
  chmod +x modem-check
  ```

**Post-Update Verification:**
- New version tested with `--version` flag before installation
- Ensures binary is executable and not corrupted
- Prevents installing broken updates

## Advanced Usage

### Disable Updates Temporarily

Set `AutoUpdateEnabled` to `false` in config:

```json
{
  "AutoUpdateEnabled": false
}
```

Or use environment variable:
```bash
export MODEMCHECK_NO_AUTO_UPDATE=1
./modem-check
```

### Switch Update Channels

Edit `config.json` and change `UpdateChannel`:

**Switch to Beta Channel:**
```json
{
  "AutoUpdateEnabled": true,
  "UpdateChannel": "beta"
}
```

**Return to Stable:**
```json
{
  "UpdateChannel": "stable"
}
```

Note: Switching from beta/test to stable won't automatically downgrade. You'll receive the next stable release.

### Force Update Check

The client checks for updates on each run. To force an immediate check:

```bash
./modem-check
# Update check happens automatically at startup
```

To see update details, check the log file:
```bash
tail -f modem-check.log | grep -i update
```

### Update Cooldown

If an update fails, the system enters a 5-minute cooldown:

```
Update to v5.8.0 was recently attempted and may have failed.
Waiting for cooldown period.
```

The cooldown prevents repeated download attempts for a broken release. After 5 minutes, updates will be attempted again.

To clear the cooldown manually:
```bash
rm .update_lock
```

## Troubleshooting

### Update Check Fails

**Symptom:** "Update check failed" in logs

**Possible Causes:**
- No internet connection
- GitHub API rate limiting
- Network firewall blocking GitHub

**Solution:**
- Check internet connectivity
- Wait 1 hour (GitHub API rate limit)
- Check firewall rules for `api.github.com`

### Signature Verification Fails

**Symptom:** "Signature verification failed"

**Possible Causes:**
- Corrupted download
- Tampered binary (security issue!)
- Outdated embedded public key

**Solution:**
- Update will be rejected automatically
- Download will be deleted
- Check GitHub releases page for announcements
- Report to maintainer if persistent

### Update Downloaded But Won't Install

**Symptom:** "Failed to install update"

**Possible Causes:**
- Insufficient disk space
- File permissions issue
- Binary currently locked (Windows)

**Solution:**
```bash
# Check disk space
df -h

# Check permissions
ls -la modem-check*

# On Windows: close all instances
# Then run installer again
```

### Binary Won't Execute After Update

**Symptom:** Program crashes immediately after update

**Automatic Rollback:**
- System will automatically rollback on next run
- Previous version restored from `.old` backup

**Manual Rollback:**
```bash
mv modem-check modem-check.broken
mv modem-check.old modem-check
chmod +x modem-check  # Unix only
```

### Wrong Platform Binary Downloaded

**Symptom:** "binary failed to execute: exec format error"

**This shouldn't happen** - platform detection is automatic

If it does:
1. Check your OS and architecture:
   ```bash
   uname -s  # OS
   uname -m  # Architecture
   ```
2. Report bug with this information
3. Manual download from GitHub releases

## Platform-Specific Notes

### Linux
- Binary stored in current directory or `/usr/local/bin`
- Requires execute permissions (`chmod +x`)
- May need sudo if installed system-wide

### macOS
- Gatekeeper may block first run of updated binary
- Allow in System Preferences → Security & Privacy
- Or use: `xattr -d com.apple.quarantine modem-check`

### Windows
- Binary may be locked if currently running
- Close all instances before update
- May trigger Windows Defender scan on first run
- `.exe` extension automatically handled

### FreeBSD/OpenBSD/NetBSD
- Works same as Linux
- Ensure compatible architecture (typically amd64 or arm64)

## Development

### Testing Update System

**Test with Pre-releases:**
```json
{
  "UpdateChannel": "test"
}
```

**Test Signature Verification:**
```bash
# Download latest release
wget https://github.com/adamkl-me/modemcheck/releases/latest/download/modem-check-linux-x64
wget https://github.com/adamkl-me/modemcheck/releases/latest/download/modem-check-linux-x64.minisig

# Verify manually
minisign -Vm modem-check-linux-x64 -P <public-key>
```

**Test Rollback:**
```bash
# Backup current version
cp modem-check modem-check.backup

# Intentionally break update
# System should rollback automatically
```

### Creating Signed Releases

See `SECURITY.md` for details on creating signed releases with Minisign.

## Security Considerations

### Threat Model

**Protected Against:**
- ✅ Man-in-the-middle attacks (signature verification)
- ✅ Compromised CDN/mirrors (signature verification)
- ✅ Malicious binaries (signature verification)
- ✅ Corrupted downloads (pre-execution testing)
- ✅ TOCTOU attacks (atomic installation)

**Not Protected Against:**
- ❌ Compromised signing key (trust model depends on key security)
- ❌ Compromised build system (if attacker has signing key)
- ❌ User-side malware (can modify binary after installation)

### Best Practices

1. **Verify Public Key**: Ensure embedded public key matches official key
2. **Use HTTPS**: Always download over HTTPS (enforced by code)
3. **Monitor Logs**: Review update logs for anomalies
4. **Backup Policy**: Keep previous version (automatic)
5. **Test Channel**: Use stable channel for production

### Key Management

The Minisign public key is embedded in the binary at compile time.

**For Users:**
- Public key is safe to share
- Verify against official documentation
- Report if signature verification fails

**For Developers:**
- Private key must be kept secure
- Use hardware security key if possible
- Never commit private key to repository
- Rotate keys if compromised

## FAQ

**Q: Can I disable automatic updates?**
A: Yes, set `AutoUpdateEnabled: false` in config.json

**Q: How often does it check for updates?**
A: Once per run, at startup

**Q: Does it update during a running check?**
A: No, updates only apply after current check completes

**Q: Can I use beta releases in production?**
A: Not recommended, but possible with `UpdateChannel: "beta"`

**Q: What happens if GitHub is down?**
A: Update check fails gracefully, current version continues working

**Q: Can I host my own update server?**
A: Not currently supported, requires code modification

**Q: Are updates signed?**
A: Yes, all releases must have valid Minisign signatures

**Q: What if I'm behind a corporate firewall?**
A: May need to allowlist `api.github.com` and `github.com`

---

*Last Updated: 2026-01-06*
*Version: 1.1.0*
