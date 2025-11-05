# ModemCheck Cloud Authentication System

## Overview

The ModemCheck Cloud now has a complete session-based authentication system with user management capabilities.

## Features

- **Session-based authentication** with 7-day session expiry
- **Password hashing** using PBKDF2-HMAC-SHA256
- **Two access levels**:
  - `basic`: Can access viewer dashboard only (port 23890)
  - `admin`: Can access both viewer and admin dashboards (ports 23890, 23891)
- **User management** in admin dashboard
- **Login/logout** functionality across all pages

## Default Credentials

**Username:** `admin`  
**Password:** `changeme`  
**Role:** `admin`

⚠️ **IMPORTANT**: You will be required to change this password on first login!

## Architecture

### Files Added

1. **`cgi-bin/auth.py`** - Core authentication module
   - Session creation and validation
   - Password hashing and verification
   - User authentication
   - Cookie management

2. **`cgi-bin/user-management.py`** - User CRUD operations (admin-only)
   - Create users
   - List users
   - Change passwords
   - Delete users

3. **`login.html`** - Login page
   - Username/password form
   - Redirects to appropriate dashboard based on role

### Files Modified

1. **`index.html`** (Viewer Dashboard)
   - Added logout button
   - Redirects to login if not authenticated

2. **`admin.html`** (Admin Dashboard)
   - Added logout button
   - Added "User Management" tab
   - Create/delete users
   - Change user passwords
   - Redirects to login if not authenticated or not admin

3. **`viewer.js`**
   - Added `checkAuth()` function
   - Added `logout()` function
   - Authentication check on page load

4. **`Dockerfile`**
   - Copies new authentication files
   - Makes CGI scripts executable

## API Endpoints

### `/cgi-bin/auth.py`

#### GET - Check Session
Returns current authentication status:
```json
{
  "authenticated": true,
  "username": "adamkl",
  "role": "admin"
}
```

#### POST - Login
Parameters:
- `action=login`
- `username` - User's username
- `password` - User's password

Response:
```json
{
  "success": true,
  "username": "adamkl",
  "role": "admin"
}
```

Sets cookie: `modemcheck_session=<session_id>`

#### POST - Logout
Parameters:
- `action=logout`

Response:
```json
{
  "success": true
}
```

Clears session cookie.

### `/cgi-bin/user-management.py` (Admin Only)

#### GET - List Users
Returns all users (without passwords):
```json
{
  "success": true,
  "users": [
    {
      "username": "adamkl",
      "role": "admin",
      "created": "2025-01-20T12:00:00"
    }
  ]
}
```

#### POST - Create User
Parameters:
- `action=create`
- `username` - New username
- `password` - New password (min 6 characters)
- `role` - Either "basic" or "admin"

Response:
```json
{
  "success": true,
  "message": "User created successfully"
}
```

#### POST - Delete User
Parameters:
- `action=delete`
- `username` - Username to delete

Response:
```json
{
  "success": true,
  "message": "User deleted successfully"
}
```

Note: Cannot delete your own account.

#### POST - Change Password
Parameters:
- `action=change_password`
- `username` - Username
- `new_password` - New password (min 6 characters)

Response:
```json
{
  "success": true,
  "message": "Password changed successfully"
}
```

## Data Storage

### Sessions
- Location: `/modemcheck-cloud/config/sessions/`
- Format: JSON files named `<session_id>.json`
- Expiry: 7 days
- Contents:
  ```json
  {
    "username": "adamkl",
    "role": "admin",
    "created": "2025-01-20T12:00:00",
    "expires": "2025-01-27T12:00:00"
  }
  ```

### Users
- Location: `/modemcheck-cloud/config/users.json`
- Format: JSON object
- Contents:
  ```json
  {
    "adamkl": {
      "password": "salt:hash",
      "role": "admin",
      "created": "2025-01-20T12:00:00"
    }
  }
  ```

## Security Features

1. **Password Hashing**: Uses PBKDF2-HMAC-SHA256 with random 32-byte salt and 100,000 iterations
2. **HttpOnly Cookies**: Session cookies are HttpOnly to prevent XSS attacks
3. **SameSite Cookies**: Cookies use SameSite=Strict to prevent CSRF attacks
4. **Session Expiry**: Sessions automatically expire after 7 days
5. **Access Control**: Admin endpoints check for admin role before allowing access
6. **Self-protection**: Users cannot delete their own accounts

## User Workflows

### First Time Setup
1. Navigate to `http://localhost:23890/` or `http://localhost:23891/`
2. You'll be redirected to `/login.html`
3. Login with `admin` / `changeme`
4. You'll be prompted to change your password immediately
5. Enter a new password (minimum 6 characters)
6. After changing password, you can create additional users in Admin Dashboard → User Management tab

### Creating a User
1. Login as admin
2. Navigate to Admin Dashboard (port 23891)
3. Click "User Management" tab
4. Fill in username, password, and select role
5. Click "Create User"

### Viewer Access (Basic Users)
1. Basic users can only access the viewer dashboard (port 23890)
2. They cannot access the admin dashboard (port 23891)
3. Attempting to access admin dashboard will redirect to login

### Admin Access
1. Admin users can access both dashboards
2. Login redirects admins to admin dashboard by default
3. Can switch between viewer and admin using port numbers

## Troubleshooting

### Cannot Login
- Check Docker logs: `sudo docker logs modemcheck-cloud`
- Verify users.json exists: `sudo docker exec modemcheck-cloud ls -la /modemcheck-cloud/config/`
- Check file permissions in container

### Session Not Persisting
- Sessions are stored in Docker volume `modemcheck-cloud_config`
- Check volume: `sudo docker volume inspect modemcheck-cloud_config`
- Sessions expire after 7 days

### Forgot Admin Password
1. Stop container: `sudo docker compose down`
2. Find and delete users.json:
   ```bash
   sudo docker volume inspect modemcheck-cloud_config | grep Mountpoint
   # Then delete the users.json file from that location
   ```
3. Restart container: `sudo docker compose up -d`
4. Default admin user will be recreated with username `admin` and password `changeme`
5. Login and you'll be forced to change the password again

## Ports

- **22557**: API upload endpoint (no authentication required for uploads)
- **23890**: Viewer dashboard (authentication required)
- **23891**: Admin dashboard (authentication required, admin role required)

## Next Steps

After authentication is working, remaining tasks:
1. Fix Xfinity modem display names (XB8 instead of Xfinity-XB8)
2. Change local storage structure (remove ModemCheck- prefix)
3. Add 14-day default date range to viewer
4. Make modem dropdown searchable
