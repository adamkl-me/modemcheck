"""
Cross-Browser Compatibility Tests for ModemCheck Cloud UI.

Tests core functionality across Chromium, Firefox, and WebKit (Safari) browsers.

Note: WebKit tests that require session cookies use a context-reuse workaround
on Linux due to limitations in WebKit's headless mode cookie handling
(Playwright issue #35269).
"""
import sys
import pytest
from playwright.async_api import Page, Playwright

from tests.ui.pages import LoginPage, AdminPage, ViewerPage

pytestmark = [pytest.mark.ui, pytest.mark.cross_browser, pytest.mark.slow]

# Test server URL
BASE_URL = "http://localhost:23894"


async def get_webkit_authenticated_context(playwright: Playwright, base_url: str):
    """Create WebKit context with pre-authenticated session.

    Workaround for WebKit headless cookie limitations on Linux (Playwright #35269).
    Instead of relying on WebKit's cookie persistence across page navigations,
    we perform login in a dedicated page, then close that page while keeping
    the context (and its session cookies) alive for subsequent test pages.

    Returns:
        Tuple of (browser, authenticated_context)
    """
    browser = await playwright.webkit.launch(headless=True)

    # Create context for login
    context = await browser.new_context(ignore_https_errors=True)
    page = await context.new_page()

    # Perform login - login_as_admin() already waits for redirect internally
    login_page = LoginPage(page, base_url)
    await login_page.navigate()
    await login_page.login_as_admin()

    # Verify login succeeded - should already be on viewer if login worked
    if "/viewer" not in page.url:
        # WebKit's cookie limitations prevent even basic login on Linux headless
        await browser.close()
        pytest.skip("WebKit on Linux headless cannot complete login (Playwright #35269)")

    # Close the login page but keep the context (which holds the session)
    await page.close()

    return browser, context


# =============================================================================
# CROSS-BROWSER BASIC TESTS
# =============================================================================

class TestCrossBrowserBasics:
    """Core functionality tests that run across all browsers (Chromium, Firefox, WebKit)."""

    @pytest.mark.asyncio
    async def test_login_page_loads(self, cross_browser_page):
        """Test login page loads correctly in each browser."""
        page, browser_type = cross_browser_page

        login_page = LoginPage(page, BASE_URL)
        await login_page.navigate()

        # Verify page loaded
        assert await login_page.is_login_page(), \
            f"Failed to load login page in {browser_type}"

        # Verify form elements are present
        assert await login_page.username_input.is_visible(), \
            f"Username input not visible in {browser_type}"
        assert await login_page.password_input.is_visible(), \
            f"Password input not visible in {browser_type}"
        assert await login_page.login_button.is_visible(), \
            f"Login button not visible in {browser_type}"

    @pytest.mark.asyncio
    async def test_login_form_submission(self, cross_browser_page, playwright_instance):
        """Test login form submission works in each browser."""
        page, browser_type = cross_browser_page

        # Use storage_state workaround for WebKit on Linux
        if browser_type == "webkit" and sys.platform == "linux":
            browser, context = await get_webkit_authenticated_context(
                playwright_instance, BASE_URL
            )
            try:
                auth_page = await context.new_page()
                # Navigate to viewer page - should work with stored session
                await auth_page.goto(f"{BASE_URL}/viewer")
                await auth_page.wait_for_load_state("domcontentloaded")
                # If authenticated, we stay on viewer page; if not, redirected to login
                viewer_page = ViewerPage(auth_page, BASE_URL)
                assert await viewer_page.is_viewer_page(), \
                    f"Login did not redirect to viewer in {browser_type}"
            finally:
                await context.close()
                await browser.close()
            return

        login_page = LoginPage(page, BASE_URL)
        await login_page.navigate()

        # Perform login
        await login_page.login_as_admin()

        # Should redirect to viewer page
        viewer_page = ViewerPage(page, BASE_URL)
        assert await viewer_page.is_viewer_page(), \
            f"Login did not redirect to viewer in {browser_type}"

    @pytest.mark.asyncio
    async def test_theme_toggle_works(self, cross_browser_page):
        """Test theme switching works in each browser."""
        page, browser_type = cross_browser_page

        login_page = LoginPage(page, BASE_URL)
        await login_page.navigate()

        # Get initial theme
        initial_theme = await login_page.get_current_theme()
        assert initial_theme == "dark", \
            f"Initial theme should be dark in {browser_type}, got {initial_theme}"

        # Toggle theme
        await login_page.toggle_theme()

        # Verify theme changed
        new_theme = await login_page.get_current_theme()
        assert new_theme == "light", \
            f"Theme should change to light in {browser_type}, got {new_theme}"

        # Verify localStorage updated
        stored_theme = await login_page.get_stored_theme()
        assert stored_theme == "light", \
            f"localStorage should be updated in {browser_type}, got {stored_theme}"

    @pytest.mark.asyncio
    async def test_navigation_between_pages(self, cross_browser_page, playwright_instance):
        """Test navigation between pages works in each browser."""
        page, browser_type = cross_browser_page

        # Use storage_state workaround for WebKit on Linux
        if browser_type == "webkit" and sys.platform == "linux":
            browser, context = await get_webkit_authenticated_context(
                playwright_instance, BASE_URL
            )
            try:
                auth_page = await context.new_page()
                # Navigate to viewer page
                await auth_page.goto(f"{BASE_URL}/viewer")
                await auth_page.wait_for_load_state("domcontentloaded")

                viewer_page = ViewerPage(auth_page, BASE_URL)

                # Navigate to admin
                await viewer_page.click_admin_button()

                # Verify admin page
                admin_page = AdminPage(auth_page, BASE_URL)
                assert await admin_page.is_admin_page(), \
                    f"Failed to navigate to admin page in {browser_type}"

                # Navigate back to viewer
                await admin_page.click_viewer_button()
                assert await viewer_page.is_viewer_page(), \
                    f"Failed to navigate back to viewer in {browser_type}"
            finally:
                await context.close()
                await browser.close()
            return

        # Login
        login_page = LoginPage(page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        # Navigate to admin
        viewer_page = ViewerPage(page, BASE_URL)
        await viewer_page.click_admin_button()

        # Verify admin page
        admin_page = AdminPage(page, BASE_URL)
        assert await admin_page.is_admin_page(), \
            f"Failed to navigate to admin page in {browser_type}"

        # Navigate back to viewer
        await admin_page.click_viewer_button()
        assert await viewer_page.is_viewer_page(), \
            f"Failed to navigate back to viewer in {browser_type}"

    @pytest.mark.asyncio
    async def test_form_validation(self, cross_browser_page):
        """Test HTML5 form validation works in each browser."""
        page, browser_type = cross_browser_page

        login_page = LoginPage(page, BASE_URL)
        await login_page.navigate()

        # Try to submit empty form
        await login_page.login_button.click()

        # Should still be on login page (validation prevented submission)
        await page.wait_for_timeout(500)
        assert await login_page.is_login_page(), \
            f"Empty form should not submit in {browser_type}"

    @pytest.mark.asyncio
    async def test_session_cookies(self, cross_browser_page, playwright_instance):
        """Test session handling works in each browser."""
        page, browser_type = cross_browser_page

        # Use storage_state workaround for WebKit on Linux
        if browser_type == "webkit" and sys.platform == "linux":
            browser, context = await get_webkit_authenticated_context(
                playwright_instance, BASE_URL
            )
            try:
                auth_page = await context.new_page()

                # Navigate to viewer and verify session established
                await auth_page.goto(f"{BASE_URL}/viewer")
                await auth_page.wait_for_load_state("domcontentloaded")
                viewer_page = ViewerPage(auth_page, BASE_URL)
                assert await viewer_page.is_viewer_page(), \
                    f"Session should be established in {browser_type}"

                # Logout
                await viewer_page.click_logout_button()

                # Should be back on login page
                await auth_page.wait_for_timeout(500)
                login_page = LoginPage(auth_page, BASE_URL)
                assert await login_page.is_login_page(), \
                    f"Session should be cleared after logout in {browser_type}"
            finally:
                await context.close()
                await browser.close()
            return

        # Login
        login_page = LoginPage(page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        # Verify session established (can access protected page)
        viewer_page = ViewerPage(page, BASE_URL)
        assert await viewer_page.is_viewer_page(), \
            f"Session should be established in {browser_type}"

        # Logout
        await viewer_page.click_logout_button()

        # Should be back on login page
        await page.wait_for_timeout(500)
        assert await login_page.is_login_page(), \
            f"Session should be cleared after logout in {browser_type}"


# =============================================================================
# FIREFOX-SPECIFIC TESTS
# =============================================================================

class TestFirefoxSpecific:
    """Tests specific to Firefox browser."""

    @pytest.mark.asyncio
    async def test_css_rendering(self, firefox_page: Page):
        """Test CSS rendering in Firefox."""
        login_page = LoginPage(firefox_page, BASE_URL)
        await login_page.navigate()

        # Verify CSS properties are applied
        bg_color = await login_page.get_background_color()
        assert bg_color, "Background color should be set in Firefox"

        text_color = await login_page.get_text_color()
        assert text_color, "Text color should be set in Firefox"

    @pytest.mark.asyncio
    async def test_form_autofocus(self, firefox_page: Page):
        """Test form autofocus behavior in Firefox."""
        login_page = LoginPage(firefox_page, BASE_URL)
        await login_page.navigate()

        # Wait for potential autofocus
        await firefox_page.wait_for_timeout(500)

        # Form should be ready for input
        await login_page.username_input.fill("test")
        value = await login_page.username_input.input_value()
        assert value == "test", "Form input should work in Firefox"


# =============================================================================
# WEBKIT-SPECIFIC TESTS
# =============================================================================

class TestWebKitSpecific:
    """Tests specific to WebKit (Safari) browser."""

    @pytest.mark.asyncio
    async def test_css_rendering(self, webkit_page: Page):
        """Test CSS rendering in WebKit."""
        login_page = LoginPage(webkit_page, BASE_URL)
        await login_page.navigate()

        # Verify CSS properties are applied
        bg_color = await login_page.get_background_color()
        assert bg_color, "Background color should be set in WebKit"

        text_color = await login_page.get_text_color()
        assert text_color, "Text color should be set in WebKit"

    @pytest.mark.asyncio
    async def test_local_storage(self, webkit_page: Page):
        """Test localStorage works in WebKit."""
        login_page = LoginPage(webkit_page, BASE_URL)
        await login_page.navigate()

        # Toggle theme to set localStorage
        await login_page.toggle_theme()

        # Verify localStorage was set
        stored = await login_page.get_stored_theme()
        assert stored == "light", "localStorage should work in WebKit"

        # Reload and verify persistence
        await webkit_page.reload()
        await webkit_page.wait_for_load_state("domcontentloaded")
        await webkit_page.wait_for_timeout(500)

        theme = await login_page.get_current_theme()
        assert theme == "light", "Theme should persist after reload in WebKit"

    @pytest.mark.asyncio
    async def test_date_inputs(self, webkit_page: Page):
        """Test date input handling in WebKit."""
        login_page = LoginPage(webkit_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        viewer_page = ViewerPage(webkit_page, BASE_URL)

        # Try setting a date value
        date_input = viewer_page.start_date_input
        if await date_input.is_visible():
            await date_input.fill("2024-01-01")
            value = await date_input.input_value()
            assert value == "2024-01-01", "Date input should work in WebKit"


# =============================================================================
# CROSS-BROWSER ADMIN TESTS
# =============================================================================

class TestCrossBrowserAdmin:
    """Admin page tests across all browsers."""

    @pytest.mark.asyncio
    async def test_admin_tabs_work(self, cross_browser_page, playwright_instance):
        """Test admin page tabs work in each browser."""
        page, browser_type = cross_browser_page

        # Use storage_state workaround for WebKit on Linux
        if browser_type == "webkit" and sys.platform == "linux":
            browser, context = await get_webkit_authenticated_context(
                playwright_instance, BASE_URL
            )
            try:
                auth_page = await context.new_page()

                # Navigate to admin page directly
                await auth_page.goto(f"{BASE_URL}/admin")
                await auth_page.wait_for_load_state("domcontentloaded")
                admin_page = AdminPage(auth_page, BASE_URL)

                # Try clicking different tabs
                await admin_page.click_tab("users")
                users_visible = await admin_page.users_section.is_visible()
                assert users_visible, f"Users tab should work in {browser_type}"

                await admin_page.click_tab("data_management")
                data_visible = await admin_page.data_management_section.is_visible()
                assert data_visible, f"Data management tab should work in {browser_type}"
            finally:
                await context.close()
                await browser.close()
            return

        # Login
        login_page = LoginPage(page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        # Navigate to admin
        admin_page = AdminPage(page, BASE_URL)
        await admin_page.navigate()

        # Try clicking different tabs
        await admin_page.click_tab("users")
        users_visible = await admin_page.users_section.is_visible()
        assert users_visible, f"Users tab should work in {browser_type}"

        await admin_page.click_tab("data_management")
        data_visible = await admin_page.data_management_section.is_visible()
        assert data_visible, f"Data management tab should work in {browser_type}"

    @pytest.mark.asyncio
    async def test_password_strength_meter(self, cross_browser_page, playwright_instance):
        """Test password strength meter works in each browser."""
        page, browser_type = cross_browser_page

        # Use storage_state workaround for WebKit on Linux
        if browser_type == "webkit" and sys.platform == "linux":
            browser, context = await get_webkit_authenticated_context(
                playwright_instance, BASE_URL
            )
            try:
                auth_page = await context.new_page()

                # Navigate to admin page directly
                await auth_page.goto(f"{BASE_URL}/admin")
                await auth_page.wait_for_load_state("domcontentloaded")
                admin_page = AdminPage(auth_page, BASE_URL)
                await admin_page.click_tab("users")

                # Type in password field
                await admin_page.new_password_input.fill("TestPassword123!")

                # Password strength meter should appear
                await auth_page.wait_for_timeout(500)
                strength_visible = await admin_page.is_password_strength_visible()
                assert strength_visible, \
                    f"Password strength meter should appear in {browser_type}"
            finally:
                await context.close()
                await browser.close()
            return

        # Login
        login_page = LoginPage(page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        # Navigate to admin users tab
        admin_page = AdminPage(page, BASE_URL)
        await admin_page.navigate()
        await admin_page.click_tab("users")

        # Type in password field
        await admin_page.new_password_input.fill("TestPassword123!")

        # Password strength meter should appear
        await page.wait_for_timeout(500)
        strength_visible = await admin_page.is_password_strength_visible()
        assert strength_visible, \
            f"Password strength meter should appear in {browser_type}"
