# Security Features

## Auto-Update Security

ModemCheck implements cryptographic signature verification for automatic updates to prevent supply chain attacks and ensure binary integrity.

### How It Works

1. **Minisign Signature Verification**: All release binaries are signed with [Minisign](https://jedisct1.github.io/minisign/), a modern cryptographic signing tool
2. **Pre-execution Validation**: Downloaded binaries are tested before installation to catch corrupted or incompatible versions
3. **Atomic Updates**: The update process is designed to prevent race conditions that could leave the system in a broken state
4. **Automatic Rollback**: If an update fails, the system automatically restores the previous working version

### Threat Protection

The auto-update mechanism protects against:

- **Man-in-the-Middle (MitM) Attacks**: Signature verification prevents execution of tampered binaries
- **GitHub Account Compromise**: Malicious binaries uploaded by attackers will fail signature verification
- **CDN/DNS Hijacking**: Any binary not signed with our private key will be rejected
- **Corrupted Downloads**: Pre-execution testing catches broken downloads before installation
- **TOCTOU Race Conditions**: Atomic update flow prevents system breakage during updates

## For Developers: Building Signed Releases

### First-Time Setup

1. **Install Minisign**:
   ```bash
   # macOS
   brew install minisign

   # Debian/Ubuntu
   apt-get install minisign

   # Fedora
   dnf install minisign

   # Arch Linux
   pacman -S minisign
   ```

2. **Generate Signing Keys** (automatic):
   ```bash
   make setup-keys
   ```

   This will:
   - Generate a Minisign key pair in `.signing-keys/`
   - Prompt you to set a password (recommended for production)
   - Automatically embed the public key in the source code
   - Remind you to backup the secret key securely

3. **Backup Your Keys**:
   ```bash
   # CRITICAL: Store your secret key securely!
   cp .signing-keys/minisign.key /secure/backup/location/
   ```

   ⚠️ **WARNING**: If you lose the secret key, you cannot sign future releases!

### Building Releases

The build process now automatically signs all binaries:

```bash
# Cross-compile and sign for all platforms
make cross-compile

# Or use the default target
make
```

This will:
1. Check if keys exist (generate if needed)
2. Detect if your key is password-protected
3. **Prompt for password ONCE** (if needed) - used for all binaries
4. Build binaries for all platforms
5. Automatically sign each binary with Minisign
6. Generate `.minisig` signature files alongside each binary

**Note**: The password is stored in memory only during the build process and never written to disk.

### Release Checklist

When creating a GitHub release:

- [ ] Build all binaries: `make cross-compile`
- [ ] Verify signatures were created: `ls dist/*.minisig`
- [ ] Upload **BOTH** binaries AND `.minisig` files to GitHub release
- [ ] Test auto-update on at least one platform before announcing

Example file structure for release:
```
modem-check-linux-x64
modem-check-linux-x64.minisig
modem-check-linux-arm64
modem-check-linux-arm64.minisig
modem-check-darwin-x64
modem-check-darwin-x64.minisig
...
```

### Manual Signing

To sign a specific binary:

```bash
make sign-binary BINARY=path/to/binary
```

### Key Management

**Rotating Keys** (if compromised):

1. Generate new keys:
   ```bash
   make clean-all  # Removes old keys
   make setup-keys # Generates new keys
   ```

2. The new public key is automatically embedded in source

3. Release a new version with the new keys

4. Old clients will need manual update (they have the old public key)

**Viewing Current Public Key**:

```bash
cat .signing-keys/minisign.pub
```

### CI/CD Integration

For automated builds (GitHub Actions, etc.):

1. **Store secret key as a repository secret**:
   - GitHub Settings → Secrets → Add `MINISIGN_SECRET_KEY`
   - Paste the contents of `.signing-keys/minisign.key`

2. **Add password as a secret** (if key is password-protected):
   - Add `MINISIGN_PASSWORD` secret

3. **In your workflow**, restore the key before building:
   ```yaml
   - name: Setup signing key
     run: |
       mkdir -p .signing-keys
       echo "${{ secrets.MINISIGN_SECRET_KEY }}" > .signing-keys/minisign.key
       # For public key, extract from source or store separately

   - name: Build and sign releases
     run: make cross-compile
     env:
       # If password-protected:
       MINISIGN_PASSWORD: ${{ secrets.MINISIGN_PASSWORD }}
   ```

## For Users: Verifying Downloads

Users can manually verify downloaded binaries using the public key:

```bash
# Install minisign
brew install minisign  # or apt-get, dnf, etc.

# Download both the binary and signature
# Public key is embedded in the source or available on our website

# Verify signature
minisign -Vm modem-check-linux-x64 -P <public_key>
```

The public key is available:
- Embedded in the client source code (`modemcheck-client/updater.go`)
- In `.signing-keys/minisign.pub` in the repository (if keys generated)

## Cloud Server Security Enhancements

The ModemCheck cloud server (FastAPI v2) includes comprehensive security features:

### Authentication & Session Security
- **Argon2id password hashing** (64MB memory, 3 iterations) with automatic upgrade from PBKDF2
- **Redis session management** with 1-hour sliding window
- **Device fingerprinting** (SHA256 hash of user-agent + IP) to detect session hijacking
- **Session anomaly detection** logs IP changes and user-agent mismatches
- **Concurrent session limits** (max 5 per user) with automatic termination of oldest sessions
- **Account lockout** after 5 failed login attempts (30-minute lockout)
- **Common password prevention** (10,000+ blocked passwords)

### API Security
- **Dual-layer rate limiting**:
  - IP-based: 30/min (auth), 60/min (upload), 300/sec (API)
  - Per-user: 100 requests/hour across all IPs (prevents multi-IP abuse)
- **CSRF protection** with token-based validation for all state-changing operations
- **HMAC-SHA256 signatures** for client uploads with replay attack prevention
- **Timing-safe comparisons** for passwords and API keys

### Data Security
- **Input validation** with Pydantic schemas
- **SQL injection prevention** via SQLAlchemy ORM
- **XSS protection** with Content-Security-Policy headers
- **Path traversal protection** for file operations
- **Audit logging** with 90-day retention policy
- **Automated backups** (daily PostgreSQL + Redis with verification)

For complete cloud server security documentation, see [cloudserver/README.md](cloudserver/README.md).

## Security Disclosure

If you discover a security vulnerability, please email security@yourdomain.com or open a private security advisory on GitHub.

**Do NOT open public issues for security vulnerabilities.**

## Security Updates

- **v5.7.2** (upcoming): Added Minisign signature verification and TOCTOU protection
- Future versions will require signed binaries to update

## Technical Details

### Update Flow

1. Client checks GitHub API for latest release
2. Downloads binary to temporary location
3. Downloads corresponding `.minisig` signature file
4. **Verifies signature** using embedded public key (CRITICAL STEP)
5. Tests binary can execute (`--version` check)
6. Creates backup of current binary
7. Atomically replaces current binary with new version
8. Restarts with new version
9. On next run, verifies update succeeded
10. If failed, automatically rolls back to backup

### Cryptographic Details

- **Algorithm**: Ed25519 (via Minisign)
- **Key Size**: 256-bit
- **Signature Format**: Minisign format with trusted comment
- **Public Key Embedding**: Hardcoded constant in binary

### Failure Modes

The update mechanism has multiple safety mechanisms:

1. **Signature verification fails** → Update aborted, error logged
2. **Download fails** → Temp files cleaned up, current binary untouched
3. **Binary won't execute** → Installation aborted, rollback performed
4. **Update process interrupted** → Next run detects failed update, attempts rollback
5. **Rollback fails** → Manual intervention required (backup preserved as `.old`)

## References

- [Minisign Documentation](https://jedisct1.github.io/minisign/)
- [go-minisign Library](https://github.com/jedisct1/go-minisign)
- [Supply Chain Attack Prevention](https://owasp.org/www-community/attacks/Supply_Chain_Attack)
- [Software Update Security Best Practices](https://theupdateframework.io/)

## Attribution

The auto-update security implementation uses:
- **[Minisign](https://jedisct1.github.io/minisign/)** by Frank Denis (ISC License) - Build-time signing tool
- **[go-minisign](https://github.com/jedisct1/go-minisign)** by Frank Denis (BSD-2-Clause License) - Runtime signature verification

See [THIRD-PARTY-LICENSES.md](THIRD-PARTY-LICENSES.md) for complete license information.
