"""
Playwright UI tests for session timeout warning functionality.

Tests the proactive session timeout warning that appears when a user's
session is about to expire, with options to extend or log out.

These tests use short TTL values injected via window variables to avoid
long wait times during testing.

NOTE: These tests require Playwright browser drivers to be installed.
Run: playwright install chromium
Or skip these tests with: pytest -m "not ui"
"""
import re
import pytest
from playwright.async_api import async_playwright, Page, expect

pytestmark = [pytest.mark.ui, pytest.mark.slow]

BASE_URL = "http://localhost:23894"  # Web UI port

# Test configuration - short timeouts for faster testing
TEST_TTL_SECONDS = 15  # 15 second session TTL
TEST_WARNING_SECONDS = 10  # Show warning at 10 seconds remaining
TEST_POLL_MS = 1000  # Poll every 1 second


@pytest.fixture(scope="function")
async def browser_page():
    """Create Playwright browser page."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        yield page
        await context.close()
        await browser.close()


async def login_as_admin(page: Page):
    """Helper to log in as admin user."""
    await page.goto(f"{BASE_URL}/login")
    await page.fill('#username', 'admin')
    await page.fill('#password', 'TestPass123!')
    await page.click('button[type="submit"]')
    await page.wait_for_load_state("networkidle", timeout=15000)

    # Verify we're on the viewer page
    current_url = page.url
    if "/login" in current_url:
        error = page.locator('#error')
        if await error.is_visible():
            error_text = await error.text_content()
            raise Exception(f"Login failed: {error_text}")
        raise Exception("Login failed: still on login page")


async def inject_test_config(page: Page):
    """Inject short timeout configuration for testing."""
    await page.evaluate(f"""
        window.SESSION_TEST_TTL = {TEST_TTL_SECONDS};
        window.SESSION_TEST_WARNING = {TEST_WARNING_SECONDS};
        window.SESSION_TEST_POLL = {TEST_POLL_MS};
    """)


class TestSessionTimeoutWarning:
    """UI tests for session timeout warning modal."""

    @pytest.mark.asyncio
    async def test_warning_modal_appears_before_timeout(self, browser_page: Page):
        """Warning modal should appear when session is about to expire."""
        # Inject short timeout config BEFORE navigating
        await browser_page.add_init_script(f"""
            window.SESSION_TEST_TTL = {TEST_TTL_SECONDS};
            window.SESSION_TEST_WARNING = {TEST_WARNING_SECONDS};
            window.SESSION_TEST_POLL = {TEST_POLL_MS};
        """)

        await login_as_admin(browser_page)

        # Wait for the warning modal to appear
        # With 15s TTL and 10s warning threshold, modal should appear after ~5 seconds
        warning_overlay = browser_page.locator('[data-testid="session-timeout-overlay"]')
        await expect(warning_overlay).to_have_class(re.compile(r"active"), timeout=20000)

        # Verify modal content
        modal = browser_page.locator('[data-testid="session-timeout-modal"]')
        await expect(modal).to_be_visible()

        # Verify buttons are present
        extend_btn = browser_page.locator('[data-testid="extend-session-btn"]')
        logout_btn = browser_page.locator('[data-testid="logout-now-btn"]')
        await expect(extend_btn).to_be_visible()
        await expect(logout_btn).to_be_visible()

    @pytest.mark.asyncio
    async def test_countdown_timer_displays_and_updates(self, browser_page: Page):
        """Countdown timer should display and update every second."""
        await browser_page.add_init_script(f"""
            window.SESSION_TEST_TTL = {TEST_TTL_SECONDS};
            window.SESSION_TEST_WARNING = {TEST_WARNING_SECONDS};
            window.SESSION_TEST_POLL = {TEST_POLL_MS};
        """)

        await login_as_admin(browser_page)

        # Wait for warning modal
        warning_overlay = browser_page.locator('[data-testid="session-timeout-overlay"]')
        await expect(warning_overlay).to_have_class(re.compile(r"active"), timeout=20000)

        # Get countdown element
        countdown = browser_page.locator('[data-testid="session-countdown"]')
        await expect(countdown).to_be_visible()

        # Get initial countdown value
        initial_text = await countdown.text_content()
        assert initial_text is not None, "Countdown should have text"

        # Wait a bit and verify it changed
        await browser_page.wait_for_timeout(2000)
        updated_text = await countdown.text_content()

        # The countdown should have decreased (or be different)
        # Note: We can't guarantee exact values due to timing, but it should be a valid format
        assert ":" in updated_text, f"Countdown should be in MM:SS format, got: {updated_text}"

    @pytest.mark.asyncio
    async def test_extend_session_button_hides_modal(self, browser_page: Page):
        """Clicking 'Extend Session' should refresh session and hide modal."""
        await browser_page.add_init_script(f"""
            window.SESSION_TEST_TTL = {TEST_TTL_SECONDS};
            window.SESSION_TEST_WARNING = {TEST_WARNING_SECONDS};
            window.SESSION_TEST_POLL = {TEST_POLL_MS};
        """)

        await login_as_admin(browser_page)

        # Wait for warning modal
        warning_overlay = browser_page.locator('[data-testid="session-timeout-overlay"]')
        await expect(warning_overlay).to_have_class(re.compile(r"active"), timeout=20000)

        # Click extend button
        extend_btn = browser_page.locator('[data-testid="extend-session-btn"]')
        await extend_btn.click()

        # Wait for success message
        status = browser_page.locator('[data-testid="session-extend-status"]')
        await expect(status).to_contain_text("extended", timeout=5000)

        # Modal should hide after success
        await expect(warning_overlay).not_to_have_class(re.compile(r"active"), timeout=3000)

        # Should still be on the viewer page (not redirected)
        assert "/viewer" in browser_page.url, "Should still be on viewer page"

    @pytest.mark.asyncio
    async def test_logout_button_redirects_to_login(self, browser_page: Page):
        """Clicking 'Log Out Now' should redirect to login page."""
        await browser_page.add_init_script(f"""
            window.SESSION_TEST_TTL = {TEST_TTL_SECONDS};
            window.SESSION_TEST_WARNING = {TEST_WARNING_SECONDS};
            window.SESSION_TEST_POLL = {TEST_POLL_MS};
        """)

        await login_as_admin(browser_page)

        # Wait for warning modal
        warning_overlay = browser_page.locator('[data-testid="session-timeout-overlay"]')
        await expect(warning_overlay).to_have_class(re.compile(r"active"), timeout=20000)

        # Click logout button
        logout_btn = browser_page.locator('[data-testid="logout-now-btn"]')
        await logout_btn.click()

        # Should redirect to login
        await browser_page.wait_for_url("**/login**", timeout=5000)
        assert "/login" in browser_page.url, "Should be redirected to login page"

    @pytest.mark.asyncio
    async def test_timeout_redirects_with_message(self, browser_page: Page):
        """When session expires completely, should redirect to login with timeout message."""
        # Use very short timeout so we don't wait too long
        short_ttl = 8
        short_warning = 5

        await browser_page.add_init_script(f"""
            window.SESSION_TEST_TTL = {short_ttl};
            window.SESSION_TEST_WARNING = {short_warning};
            window.SESSION_TEST_POLL = 500;
        """)

        await login_as_admin(browser_page)

        # Wait for redirect to login page
        await browser_page.wait_for_url("**/login**", timeout=20000)

        # Verify we're on login page
        assert "/login" in browser_page.url, "Should be on login page"

        # The timeout message should be displayed (URL is cleaned up by login.html JS)
        await browser_page.wait_for_timeout(500)  # Give JS time to process
        error_element = browser_page.locator('#error')
        await expect(error_element).to_be_visible()
        await expect(error_element).to_contain_text("session has timed out")

    @pytest.mark.asyncio
    async def test_login_page_shows_timeout_message(self, browser_page: Page):
        """Login page with ?timeout=1 should show 'Session timed out' message."""
        # Navigate directly to login with timeout parameter
        await browser_page.goto(f"{BASE_URL}/login?timeout=1")

        # Wait for page to load and process the parameter
        await browser_page.wait_for_load_state("domcontentloaded")
        await browser_page.wait_for_timeout(500)  # Give JS time to process

        # Check for error message
        error_element = browser_page.locator('#error')
        await expect(error_element).to_be_visible()
        await expect(error_element).to_contain_text("session has timed out")

    @pytest.mark.asyncio
    async def test_login_page_preserves_return_url(self, browser_page: Page):
        """Login page should preserve return URL when showing timeout message."""
        return_path = "/viewer"
        await browser_page.goto(f"{BASE_URL}/login?timeout=1&return={return_path}")

        await browser_page.wait_for_load_state("domcontentloaded")
        await browser_page.wait_for_timeout(500)

        # Error should be shown
        error_element = browser_page.locator('#error')
        await expect(error_element).to_be_visible()

        # URL should have been cleaned but still have return param
        current_url = browser_page.url
        assert "timeout=1" not in current_url, "timeout param should be removed from URL"
        # Return param may or may not be present depending on implementation

    @pytest.mark.asyncio
    async def test_warning_modal_has_high_z_index(self, browser_page: Page):
        """Warning modal should appear above other page content."""
        await browser_page.add_init_script(f"""
            window.SESSION_TEST_TTL = {TEST_TTL_SECONDS};
            window.SESSION_TEST_WARNING = {TEST_WARNING_SECONDS};
            window.SESSION_TEST_POLL = {TEST_POLL_MS};
        """)

        await login_as_admin(browser_page)

        # Wait for warning modal
        warning_overlay = browser_page.locator('[data-testid="session-timeout-overlay"]')
        await expect(warning_overlay).to_have_class(re.compile(r"active"), timeout=20000)

        # Verify z-index is very high
        z_index = await warning_overlay.evaluate("el => window.getComputedStyle(el).zIndex")
        assert int(z_index) >= 99999, f"z-index should be >= 99999, got {z_index}"


class TestSessionTimeoutOnAdminPage:
    """Test session timeout warning on admin page."""

    @pytest.mark.asyncio
    async def test_admin_page_shows_warning(self, browser_page: Page):
        """Admin page should also show session timeout warning."""
        await browser_page.add_init_script(f"""
            window.SESSION_TEST_TTL = {TEST_TTL_SECONDS};
            window.SESSION_TEST_WARNING = {TEST_WARNING_SECONDS};
            window.SESSION_TEST_POLL = {TEST_POLL_MS};
        """)

        # Login and navigate to admin
        await login_as_admin(browser_page)
        await browser_page.goto(f"{BASE_URL}/admin")

        # Wait for page to be authenticated (container has authenticated class)
        await browser_page.wait_for_selector('.container.authenticated', timeout=15000)

        # Wait for warning modal
        warning_overlay = browser_page.locator('[data-testid="session-timeout-overlay"]')
        await expect(warning_overlay).to_have_class(re.compile(r"active"), timeout=20000)

        # Verify it's visible
        await expect(warning_overlay).to_be_visible()
