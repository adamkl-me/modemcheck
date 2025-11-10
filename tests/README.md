# Modemcheck Testing Framework

Comprehensive automated testing suite for the Modemcheck project that tests all components without leaving lasting traces on data structures.

## Overview

This testing framework provides:

- **Go Unit Tests** - Test individual functions and components in the modemcheck-client
- **Python Integration Tests** - Test cloud API endpoints and database operations
- **Docker Test Environment** - Isolated test environment with separate databases
- **End-to-End Tests** - Test complete workflows from upload to database to viewer
- **Automatic Cleanup** - All tests clean up after themselves

## Test Architecture

```
tests/
├── README.md                    # This file
├── requirements.txt             # Python test dependencies
│
├── test_env_setup.sh           # Test environment setup and orchestration
├── test_cloud_api.py           # Python integration tests
├── init_test_data.py           # Test data initialization
│
└── [Generated at runtime]
    ├── test-data/              # Isolated test data (auto-cleaned)
    │   ├── datafiles/          # Test file uploads
    │   ├── data/               # Test databases
    │   └── config/             # Test users and API keys
    └── coverage/               # Test coverage reports
```

## Prerequisites

### Required Software

1. **Go 1.19+** - For Go unit tests
   ```bash
   go version
   ```

2. **Python 3.9+** - For integration tests
   ```bash
   python3 --version
   ```

3. **Docker & Docker Compose** - For test environment
   ```bash
   docker --version
   docker compose version
   ```

4. **curl** - For E2E tests
   ```bash
   curl --version
   ```

### Install Test Dependencies

```bash
# Python dependencies
cd tests
pip3 install -r requirements.txt

# Or using a virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Quick Start

### Run All Tests (Recommended)

This runs the complete test suite with automatic setup and cleanup:

```bash
cd tests
./test_env_setup.sh all
```

This will:
1. Set up isolated test environment
2. Start test Docker container
3. Initialize test databases
4. Run Go unit tests
5. Run Python integration tests
6. Run end-to-end tests
7. Clean up all test data

### Run Individual Test Suites

#### Go Unit Tests Only

```bash
cd /home/adamkl/projects/modemcheck
go test -v -cover ./...
```

Test coverage:
```bash
go test -coverprofile=coverage.out ./...
go tool cover -html=coverage.out
```

#### Python Integration Tests Only

```bash
cd tests
python3 -m pytest test_cloud_api.py -v
```

With coverage:
```bash
pytest test_cloud_api.py -v --cov --cov-report=html
```

#### Functional Tests Only

The test_env_setup.sh script includes functional tests when run with 'all' or 'test' options:

```bash
cd tests
./test_env_setup.sh all
```

## Test Environment Management

### Setup Test Environment

Creates isolated test environment and starts container:

```bash
cd tests
./test_env_setup.sh setup
```

This creates:
- Test Docker container on different ports (22558, 23892, 23893)
- Isolated test databases (not production)
- Test users: `testuser` / `testadmin`
- Test API keys: `test_key_active` / `test_key_inactive`

### Cleanup Test Environment

Removes all test data and stops container:

```bash
cd tests
./test_env_setup.sh cleanup
```

This removes:
- Test Docker container
- Test data directory (`cloudserver/test-data/`)
- All uploaded files
- All test databases
- All test sessions

**Note:** Production data is never affected.

### Manual Test Environment

For manual testing or debugging:

```bash
# Setup environment
cd tests
./test_env_setup.sh setup

# Test environment is now available:
# - Upload API:  http://localhost:22558/cgi-bin/upload.py
# - Viewer:      http://localhost:23892
# - Admin:       http://localhost:23893

# Manual testing...
curl -X POST \
  -F "api_key=test_key_active" \
  -F "modem_id=CODA56-AABBCC112233" \
  -F "filename=test.json" \
  -F "file=@test.json" \
  http://localhost:22558/cgi-bin/upload.py

# When done, cleanup
./test_env_setup.sh cleanup
```

## Test Suites

### 1. Go Unit Tests

Tests core Go functionality in the modemcheck-client without requiring external services.

**Test Coverage:**
- Configuration loading and validation
- Upload queue operations (save, load, add, remove)
- Queue size limits and age-based cleanup
- Modem detection logic
- MAC address parsing (CODA, DM1000, Xfinity)
- OFDMA data extraction
- Upload format validation
- Utility functions

**Run:**
```bash
cd /home/adamkl/projects/modemcheck
go test -v ./...
```

**Example Output:**
```
=== RUN   TestNewModemCheck
--- PASS: TestNewModemCheck (0.00s)
=== RUN   TestLoadConfigFile
--- PASS: TestLoadConfigFile (0.01s)
=== RUN   TestUploadQueueOperations
--- PASS: TestUploadQueueOperations (0.02s)
...
PASS
coverage: 65.4% of statements
```

### 2. Python Integration Tests (test_cloud_api.py)

Tests cloud API components with isolated test databases.

**Test Coverage:**
- Password hashing and verification
- Session creation and validation
- Session expiry handling
- Database insert operations
- Duplicate filename prevention
- Modem ID querying
- Date range queries
- Audit logging
- API key validation
- File upload validation
- Filename and modem_id regex validation
- Path traversal prevention
- Data cleanup functions

**Run:**
```bash
cd tests
pytest test_cloud_api.py -v
```

**Example Output:**
```
tests/test_cloud_api.py::TestAuthentication::test_password_hashing PASSED
tests/test_cloud_api.py::TestAuthentication::test_session_creation PASSED
tests/test_cloud_api.py::TestDatabaseOperations::test_insert_check PASSED
...
==================== 25 passed in 2.34s ====================
```

### 3. Integrated Test Suite (test_env_setup.sh)

The test_env_setup.sh script orchestrates the complete test workflow including environment setup, running tests, and cleanup.

**Test Coverage:**
- Upload with valid/invalid/inactive API keys
- Path traversal prevention
- Invalid filename rejection
- Large file rejection (>10MB)
- Duplicate filename prevention
- Missing required fields
- Database API authentication
- Data integrity after upload
- Audit logging verification
- Security validation

**Run:**
```bash
cd tests
./test_env_setup.sh all
```

**Available Commands:**
- `./test_env_setup.sh setup` - Setup test environment only
- `./test_env_setup.sh test` - Run tests (requires setup first)
- `./test_env_setup.sh cleanup` - Clean up test environment
- `./test_env_setup.sh all` - Complete workflow (setup, test, cleanup)

**Example Output:**
```
Setting up test environment...
Creating test volumes...
Starting test container...
Initializing test databases...
Running Python integration tests...
All tests passed!
Cleaning up test environment...
```

## Test Data and Isolation

### How Tests Stay Isolated

1. **Separate Docker Container**
   - Test container: `modemcheck-cloud-test`
   - Different ports: 22558, 23892, 23893
   - Separate network: `modemcheck-test` (172.26.0.0/16)

2. **Separate Databases**
   - Test DB: `cloudserver/test-data/data/modemcheck.db`
   - Production DB: `cloudserver/data/modemcheck.db`
   - Never mixed or shared

3. **Separate File Storage**
   - Test files: `cloudserver/test-data/datafiles/`
   - Production files: `cloudserver/datafiles/`

4. **Automatic Cleanup**
   - All test data removed after tests
   - Test container stopped and removed
   - No traces left in production

### Test Data Lifecycle

```
Setup Phase:
├── Create test-data/ directory
├── Create test databases
├── Create test users and API keys
└── Start test container

Test Phase:
├── Upload test files
├── Import to test database
├── Run queries and validations
└── Verify results

Cleanup Phase:
├── Stop test container
├── Remove test-data/ directory
└── Production data unchanged ✓
```

## Continuous Integration

### GitHub Actions Example

Create `.github/workflows/test.yml`:

```yaml
name: Modemcheck Tests

on:
  push:
    branches: [ main, develop ]
  pull_request:
    branches: [ main ]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
    - uses: actions/checkout@v3

    - name: Set up Go
      uses: actions/setup-go@v4
      with:
        go-version: '1.21'

    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.11'

    - name: Install Python dependencies
      run: |
        cd tests
        pip install -r requirements.txt

    - name: Run all tests
      run: |
        cd tests
        ./test_env_setup.sh all

    - name: Upload coverage
      uses: codecov/codecov-action@v3
      if: always()
```

## Troubleshooting

### Test Container Won't Start

```bash
# Check if production container is using the same ports
docker ps | grep modemcheck

# Stop production container temporarily
cd cloudserver
docker compose down

# Try starting test environment again
cd ../tests
./test_env_setup.sh setup
```

### Tests Fail with "Connection Refused"

```bash
# Check if test container is running
docker ps | grep modemcheck-cloud-test

# Check container logs
docker logs modemcheck-cloud-test

# Restart test environment
cd tests
./test_env_setup.sh cleanup
./test_env_setup.sh setup
```

### Database Errors in Tests

```bash
# Check database permissions
docker exec modemcheck-cloud-test ls -la /modemcheck-cloud/data/

# Reinitialize databases
docker exec modemcheck-cloud-test python3 <<EOF
import sys
sys.path.insert(0, '/modemcheck-cloud/cgi-bin')
from db_schema import init_database
init_database()
EOF
```

### Go Tests Fail to Build

```bash
# Ensure you're in the project root
cd /home/adamkl/projects/modemcheck

# Clean build cache
go clean -cache

# Run tests again
go test -v ./...
```

### Python Import Errors

```bash
# Ensure dependencies are installed
cd tests
pip install -r requirements.txt

# Check Python path
python3 -c "import sys; print(sys.path)"

# Try running tests with explicit path
PYTHONPATH=/home/adamkl/projects/modemcheck/cloudserver/cgi-bin pytest test_cloud_api.py -v
```

### Cleanup Not Working

```bash
# Manual cleanup
cd cloudserver
docker compose -f docker-compose.test.yml down -v
rm -rf test-data/

# Force remove container
docker rm -f modemcheck-cloud-test
```

## Writing New Tests

### Adding Go Unit Tests

Add tests to the modemcheck-client package:

```go
func TestYourNewFeature(t *testing.T) {
    // Setup
    // ... initialize test data

    // Test
    result := yourFunction()

    // Assert
    if result != expected {
        t.Errorf("Expected %v, got %v", expected, result)
    }

    // Cleanup (if needed)
    // ...
}
```

### Adding Python Integration Tests

Edit `tests/test_cloud_api.py`:

```python
def test_your_new_feature(test_env):
    """Test your new feature"""
    # test_env provides isolated environment

    # Setup test data
    # ... your test code ...

    # Assert
    assert result == expected

    # Cleanup happens automatically via test_env fixture
```

### Adding Integration Tests

You can extend the test framework by adding new test functions to `test_cloud_api.py` or by creating additional test scripts that follow the same pattern as `test_env_setup.sh`.

## Test Coverage Goals

- **Go Code**: > 70% coverage
- **Python Code**: > 80% coverage
- **API Endpoints**: 100% coverage
- **Security Features**: 100% coverage

Check coverage:

```bash
# Go coverage
go test -coverprofile=coverage.out ./...
go tool cover -func=coverage.out

# Python coverage
cd tests
pytest test_cloud_api.py --cov --cov-report=term-missing
```

## Best Practices

1. **Always run full test suite before commits**
   ```bash
   cd tests && ./test_env_setup.sh all
   ```

2. **Write tests for new features**
   - Add Go tests for client-side logic
   - Add Python tests for server-side logic
   - Add E2E tests for complete workflows

3. **Test security features thoroughly**
   - Path traversal attempts
   - SQL injection attempts
   - Authentication bypass attempts
   - Input validation

4. **Keep tests fast**
   - Go tests: < 5 seconds
   - Python tests: < 10 seconds
   - E2E tests: < 30 seconds

5. **Cleanup is mandatory**
   - All tests must clean up after themselves
   - Use fixtures and defer statements
   - Never leave test data in production

## Performance Benchmarks

Run Go benchmarks:

```bash
go test -bench=. -benchmem ./...
```

Example output:
```
BenchmarkLoadUploadQueue-8      50000    25432 ns/op    8192 B/op    12 allocs/op
BenchmarkJSONParsing-8         100000    10245 ns/op    4096 B/op     8 allocs/op
```

## Support

If you encounter issues:

1. Check this README for troubleshooting steps
2. Check test logs: `docker logs modemcheck-cloud-test`
3. Try cleanup and restart: `./test_env_setup.sh cleanup && ./test_env_setup.sh all`
4. Review CLAUDE.md for architecture details
5. Check individual test output for specific failures

## Contributing

When contributing tests:

1. Follow existing test structure
2. Add descriptive test names
3. Include assertions for all expected behavior
4. Test both success and failure cases
5. Ensure cleanup happens automatically
6. Update this README with new test descriptions

---

**Last Updated:** 2025-11-05
**Test Framework Version:** 1.0.0
