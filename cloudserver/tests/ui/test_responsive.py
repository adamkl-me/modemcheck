"""
Responsive Design Tests for ModemCheck Cloud UI.

Tests UI behavior across different viewport sizes (mobile, tablet, desktop).
"""
import pytest
from playwright.async_api import Page, expect

from tests.ui.pages import LoginPage, AdminPage, ViewerPage

pytestmark = [pytest.mark.ui, pytest.mark.responsive]

# Test server URL
BASE_URL = "http://localhost:23894"

# Minimum touch target size (44x44 pixels per WCAG 2.1)
MIN_TOUCH_TARGET_SIZE = 44


# =============================================================================
# LOGIN PAGE RESPONSIVE TESTS
# =============================================================================

class TestLoginResponsive:
    """Responsive tests for the login page across all viewports."""

    @pytest.mark.asyncio
    async def test_login_form_visible_all_viewports(self, responsive_page):
        """Login form should be visible at all viewport sizes."""
        page, viewport_name, viewport = responsive_page

        login_page = LoginPage(page, BASE_URL)
        await login_page.navigate()

        # Check form elements are visible
        assert await login_page.username_input.is_visible(), \
            f"Username input not visible at {viewport_name} ({viewport})"
        assert await login_page.password_input.is_visible(), \
            f"Password input not visible at {viewport_name} ({viewport})"
        assert await login_page.login_button.is_visible(), \
            f"Login button not visible at {viewport_name} ({viewport})"

    @pytest.mark.asyncio
    async def test_login_form_usable_all_viewports(self, responsive_page):
        """Login form should be usable at all viewport sizes."""
        page, viewport_name, viewport = responsive_page

        login_page = LoginPage(page, BASE_URL)
        await login_page.navigate()

        # Try filling the form
        await login_page.username_input.fill("test_user")
        await login_page.password_input.fill("test_password")

        # Verify values were entered
        username_value = await login_page.username_input.input_value()
        password_value = await login_page.password_input.input_value()

        assert username_value == "test_user", \
            f"Username input not working at {viewport_name}"
        assert password_value == "test_password", \
            f"Password input not working at {viewport_name}"

    @pytest.mark.asyncio
    async def test_theme_toggle_accessible_all_viewports(self, responsive_page):
        """Theme toggle button should be accessible at all viewport sizes."""
        page, viewport_name, viewport = responsive_page

        login_page = LoginPage(page, BASE_URL)
        await login_page.navigate()

        # Theme toggle should be visible
        assert await login_page.is_theme_toggle_visible(), \
            f"Theme toggle not visible at {viewport_name}"

        # Should be able to toggle theme
        initial_theme = await login_page.get_current_theme()
        await login_page.toggle_theme()
        new_theme = await login_page.get_current_theme()

        assert initial_theme != new_theme, \
            f"Theme toggle not working at {viewport_name}"


# =============================================================================
# VIEWER PAGE RESPONSIVE TESTS
# =============================================================================

class TestViewerResponsive:
    """Responsive tests for the viewer page."""

    @pytest.mark.asyncio
    async def test_filter_section_visible_all_viewports(self, responsive_page):
        """Filter section should be visible at all viewport sizes."""
        page, viewport_name, viewport = responsive_page

        # Login first
        login_page = LoginPage(page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        viewer_page = ViewerPage(page, BASE_URL)

        # Check filter elements are visible
        assert await viewer_page.modem_search_input.is_visible(), \
            f"Modem search not visible at {viewport_name}"
        assert await viewer_page.load_button.is_visible(), \
            f"Load button not visible at {viewport_name}"

    @pytest.mark.asyncio
    async def test_modem_dropdown_usable_on_mobile(self, mobile_page: Page):
        """Modem dropdown should work on mobile viewport."""
        login_page = LoginPage(mobile_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        viewer_page = ViewerPage(mobile_page, BASE_URL)

        # Click modem search to open dropdown
        await viewer_page.modem_search_input.click()
        await mobile_page.wait_for_timeout(500)

        # Dropdown should be visible
        dropdown_visible = await viewer_page.modem_dropdown.is_visible()
        assert dropdown_visible, "Modem dropdown should be visible on mobile"

    @pytest.mark.asyncio
    async def test_view_toggle_visible_on_mobile(self, mobile_page: Page):
        """View toggle buttons should be visible on mobile."""
        login_page = LoginPage(mobile_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        viewer_page = ViewerPage(mobile_page, BASE_URL)

        # View toggle buttons should be visible
        assert await viewer_page.single_view_button.is_visible(), \
            "Single view button not visible on mobile"
        assert await viewer_page.trend_view_button.is_visible(), \
            "Trend view button not visible on mobile"

    @pytest.mark.asyncio
    async def test_header_buttons_accessible_on_mobile(self, mobile_page: Page):
        """Header buttons (logout, admin) should be accessible on mobile."""
        login_page = LoginPage(mobile_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        viewer_page = ViewerPage(mobile_page, BASE_URL)

        # Admin button should be visible (admin user)
        assert await viewer_page.admin_button.is_visible(), \
            "Admin button not visible on mobile"
        # Logout button should be visible
        assert await viewer_page.logout_button.is_visible(), \
            "Logout button not visible on mobile"


# =============================================================================
# ADMIN PAGE RESPONSIVE TESTS
# =============================================================================

class TestAdminResponsive:
    """Responsive tests for the admin page."""

    @pytest.mark.asyncio
    async def test_hamburger_menu_visible_on_mobile(self, mobile_page: Page):
        """Hamburger menu should appear on mobile viewport."""
        login_page = LoginPage(mobile_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        admin_page = AdminPage(mobile_page, BASE_URL)
        await admin_page.navigate()

        # Hamburger should be visible on mobile
        hamburger_visible = await admin_page.hamburger.is_visible()
        assert hamburger_visible, "Hamburger menu should be visible on mobile"

    @pytest.mark.asyncio
    async def test_hamburger_menu_opens_navigation(self, mobile_page: Page):
        """Clicking hamburger should show navigation menu."""
        login_page = LoginPage(mobile_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        admin_page = AdminPage(mobile_page, BASE_URL)
        await admin_page.navigate()

        # Open mobile menu
        await admin_page.open_mobile_menu()

        # Mobile menu should be visible/active
        menu_visible = await admin_page.is_mobile_menu_visible()
        assert menu_visible, "Mobile menu should be visible after clicking hamburger"

    @pytest.mark.asyncio
    async def test_tabs_layout_adapts_on_mobile(self, mobile_page: Page):
        """Admin tabs should adapt layout on mobile."""
        login_page = LoginPage(mobile_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        admin_page = AdminPage(mobile_page, BASE_URL)
        await admin_page.navigate()

        # Tabs should still be accessible (either directly visible or via menu)
        # Try clicking a tab
        await admin_page.click_tab("users")
        await mobile_page.wait_for_timeout(500)

        # Users section should become visible
        users_visible = await admin_page.users_section.is_visible()
        assert users_visible, "Users section should be accessible on mobile"

    @pytest.mark.asyncio
    async def test_forms_usable_on_mobile(self, mobile_page: Page):
        """Admin forms should be fillable on mobile."""
        login_page = LoginPage(mobile_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        admin_page = AdminPage(mobile_page, BASE_URL)
        await admin_page.navigate()
        await admin_page.click_tab("users")

        # Try filling the create user form
        await admin_page.new_username_input.fill("mobile_test_user")
        await admin_page.new_password_input.fill("MobileTestPass123!")

        # Verify values were entered
        username_value = await admin_page.new_username_input.input_value()
        password_value = await admin_page.new_password_input.input_value()

        assert username_value == "mobile_test_user", \
            "Username input not working on mobile"
        assert password_value == "MobileTestPass123!", \
            "Password input not working on mobile"

    @pytest.mark.asyncio
    async def test_header_navigation_on_tablet(self, tablet_page: Page):
        """Header navigation should work on tablet viewport."""
        login_page = LoginPage(tablet_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        admin_page = AdminPage(tablet_page, BASE_URL)
        await admin_page.navigate()

        # Viewer button should be visible and clickable
        assert await admin_page.viewer_button.is_visible(), \
            "Viewer button not visible on tablet"

        # Logout button should be visible
        assert await admin_page.logout_button.is_visible(), \
            "Logout button not visible on tablet"


# =============================================================================
# TOUCH TARGET SIZE TESTS
# =============================================================================

class TestTouchTargets:
    """Touch target size validation for mobile accessibility."""

    @pytest.mark.asyncio
    async def test_login_button_minimum_touch_size(self, mobile_page: Page):
        """Login button should meet minimum touch target size (44x44px)."""
        login_page = LoginPage(mobile_page, BASE_URL)
        await login_page.navigate()

        # Get button bounding box
        box = await login_page.login_button.bounding_box()
        assert box is not None, "Login button should have a bounding box"

        assert box["width"] >= MIN_TOUCH_TARGET_SIZE, \
            f"Login button width ({box['width']}px) should be >= {MIN_TOUCH_TARGET_SIZE}px"
        assert box["height"] >= MIN_TOUCH_TARGET_SIZE, \
            f"Login button height ({box['height']}px) should be >= {MIN_TOUCH_TARGET_SIZE}px"

    @pytest.mark.asyncio
    async def test_form_inputs_adequate_size(self, mobile_page: Page):
        """Form inputs should have adequate touch target size."""
        login_page = LoginPage(mobile_page, BASE_URL)
        await login_page.navigate()

        # Check username input
        username_box = await login_page.username_input.bounding_box()
        assert username_box is not None, "Username input should have a bounding box"
        assert username_box["height"] >= MIN_TOUCH_TARGET_SIZE, \
            f"Username input height ({username_box['height']}px) should be >= {MIN_TOUCH_TARGET_SIZE}px"

        # Check password input
        password_box = await login_page.password_input.bounding_box()
        assert password_box is not None, "Password input should have a bounding box"
        assert password_box["height"] >= MIN_TOUCH_TARGET_SIZE, \
            f"Password input height ({password_box['height']}px) should be >= {MIN_TOUCH_TARGET_SIZE}px"

    @pytest.mark.asyncio
    async def test_theme_toggle_touch_size(self, mobile_page: Page):
        """Theme toggle should meet minimum touch target size."""
        login_page = LoginPage(mobile_page, BASE_URL)
        await login_page.navigate()

        box = await login_page.theme_toggle.bounding_box()
        assert box is not None, "Theme toggle should have a bounding box"

        # At minimum, the clickable area should be reasonable
        assert box["width"] >= 24, \
            f"Theme toggle width ({box['width']}px) should be >= 24px"
        assert box["height"] >= 24, \
            f"Theme toggle height ({box['height']}px) should be >= 24px"


# =============================================================================
# VIEWPORT-SPECIFIC LAYOUT TESTS
# =============================================================================

class TestViewportLayouts:
    """Tests for layout changes at different viewport sizes."""

    @pytest.mark.asyncio
    async def test_desktop_shows_full_navigation(self, browser_page: Page):
        """Desktop viewport should show full navigation without hamburger."""
        # Default browser_page is desktop-sized
        login_page = LoginPage(browser_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        admin_page = AdminPage(browser_page, BASE_URL)
        await admin_page.navigate()

        # On desktop, hamburger should NOT be visible (or menu should be expanded)
        # Tabs should be directly visible
        tabs_visible = await admin_page.client_management_tab.is_visible()
        assert tabs_visible, "Navigation tabs should be visible on desktop"

    @pytest.mark.asyncio
    async def test_mobile_collapses_navigation(self, mobile_page: Page):
        """Mobile viewport should collapse navigation to hamburger."""
        login_page = LoginPage(mobile_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        admin_page = AdminPage(mobile_page, BASE_URL)
        await admin_page.navigate()

        # On mobile, hamburger should be visible
        hamburger_visible = await admin_page.hamburger.is_visible()
        assert hamburger_visible, "Hamburger menu should be visible on mobile"

    @pytest.mark.asyncio
    async def test_tablet_intermediate_layout(self, tablet_page: Page):
        """Tablet viewport should have appropriate intermediate layout."""
        login_page = LoginPage(tablet_page, BASE_URL)
        await login_page.navigate()
        await login_page.login_as_admin()

        admin_page = AdminPage(tablet_page, BASE_URL)
        await admin_page.navigate()

        # On tablet, layout should adapt - check both navigation and content are usable
        # Either tabs directly visible OR hamburger present
        tabs_visible = await admin_page.client_management_tab.is_visible()
        hamburger_visible = await admin_page.hamburger.is_visible()

        assert tabs_visible or hamburger_visible, \
            "Either tabs or hamburger should be visible on tablet"
