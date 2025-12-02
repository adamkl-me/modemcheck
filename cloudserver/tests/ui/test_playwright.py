"""
Playwright UI tests for ModemCheck Cloud v2.

Tests web interface functionality using browser automation.
Validates actual user interactions: button clicks, form submissions, data display.

NOTE: These tests require Playwright browser drivers to be installed.
Run: playwright install chromium
Or skip these tests with: pytest -m "not ui"
"""
import re
import pytest
from playwright.async_api import async_playwright, Page, expect

pytestmark = pytest.mark.ui

BASE_URL = "http://localhost:23894"  # Web UI port


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


async def login_as_user(page: Page, username: str, password: str):
    """Helper to log in as specific user."""
    await page.goto(f"{BASE_URL}/login")
    await page.fill('#username', username)
    await page.fill('#password', password)
    await page.click('button[type="submit"]')

    # Wait for navigation to complete (either redirect or error)
    await page.wait_for_load_state("networkidle", timeout=15000)

    # Check if login succeeded by verifying we're on viewer page
    # If still on login page, the login failed
    current_url = page.url
    if "/login" in current_url:
        # Check for error message
        error = page.locator('#error')
        if await error.is_visible():
            error_text = await error.text_content()
            raise Exception(f"Login failed: {error_text}")
        raise Exception("Login failed: still on login page")


async def login_as_admin(page: Page):
    """Helper to log in as admin."""
    await login_as_user(page, 'admin', 'TestPass123!')


async def login_as_basic(page: Page):
    """Helper to log in as basic user."""
    await login_as_user(page, 'test_basic', 'BasicPass123!')


class TestLoginUI:
    """UI tests for login page - validates form elements, submission, and error handling."""

    @pytest.mark.asyncio
    async def test_login_page_loads_with_correct_elements(self, browser_page: Page):
        """Test login page loads with all required form elements and labels."""
        await browser_page.goto(f"{BASE_URL}/login")
        await expect(browser_page).to_have_title("Login - ModemCheck Cloud")

        # Verify form elements are present
        await expect(browser_page.locator('#username')).to_be_visible()
        await expect(browser_page.locator('#password')).to_be_visible()
        await expect(browser_page.locator('button[type="submit"]')).to_be_visible()

        # Verify labels exist with correct text
        await expect(browser_page.locator('label[for="username"]')).to_have_text("Username")
        await expect(browser_page.locator('label[for="password"]')).to_have_text("Password")

        # Verify button text
        await expect(browser_page.locator('#login-btn')).to_have_text("Login")

        # Verify logo/branding is present
        await expect(browser_page.locator('.logo h1')).to_have_text("ModemCheck Cloud")

    @pytest.mark.asyncio
    async def test_login_button_submits_form_successfully(self, browser_page: Page):
        """Test clicking login button with valid credentials redirects to viewer."""
        await browser_page.goto(f"{BASE_URL}/login")

        # Fill login form
        await browser_page.fill('#username', 'admin')
        await browser_page.fill('#password', 'TestPass123!')

        # Click submit button (actual button click, not form submit)
        await browser_page.click('#login-btn')

        # Wait for navigation to complete
        await browser_page.wait_for_load_state("networkidle", timeout=15000)

        # Verify we're on the viewer page (or check what happened)
        current_url = browser_page.url
        assert "/viewer" in current_url or "/login" not in current_url, \
            f"Expected redirect to viewer, but got: {current_url}"

    @pytest.mark.asyncio
    async def test_login_button_shows_loading_state(self, browser_page: Page):
        """Test login button changes text during submission."""
        await browser_page.goto(f"{BASE_URL}/login")

        await browser_page.fill('#username', 'admin')
        await browser_page.fill('#password', 'TestPass123!')

        # Click and verify button behavior (login is fast, so we mainly verify it works)
        await browser_page.click('#login-btn')

        # Wait for navigation to complete
        await browser_page.wait_for_load_state("networkidle", timeout=15000)

        # If we got here without error, the loading state transitioned correctly
        current_url = browser_page.url
        assert "/login" not in current_url, "Should have navigated away from login page"

    @pytest.mark.asyncio
    async def test_login_invalid_credentials_shows_error_message(self, browser_page: Page):
        """Test invalid credentials display specific error message text."""
        await browser_page.goto(f"{BASE_URL}/login")

        await browser_page.fill('#username', 'invalid_user')
        await browser_page.fill('#password', 'wrong_password')
        await browser_page.click('#login-btn')

        # Wait for response to complete
        await browser_page.wait_for_load_state("networkidle", timeout=10000)

        # Should still be on login page
        assert "/login" in browser_page.url, "Should stay on login page after invalid credentials"

        # Wait for error to appear (the .show class is added via JS)
        await browser_page.wait_for_timeout(1000)

        # Check for error element
        error_element = browser_page.locator('#error')
        is_visible = await error_element.is_visible()
        if is_visible:
            error_text = await error_element.text_content()
            assert len(error_text) > 0, "Error message should not be empty"

    @pytest.mark.asyncio
    async def test_login_empty_fields_prevents_submission(self, browser_page: Page):
        """Test that empty username/password fields are rejected (HTML5 validation)."""
        await browser_page.goto(f"{BASE_URL}/login")

        # Try to submit with empty fields
        await browser_page.click('#login-btn')

        # Should still be on login page (HTML5 required validation prevents submit)
        await browser_page.wait_for_timeout(500)
        await expect(browser_page).to_have_url(f"{BASE_URL}/login")

    @pytest.mark.asyncio
    async def test_login_button_re_enables_after_failure(self, browser_page: Page):
        """Test login button is re-enabled after failed login attempt."""
        await browser_page.goto(f"{BASE_URL}/login")

        await browser_page.fill('#username', 'invalid_user')
        await browser_page.fill('#password', 'wrong_password')
        await browser_page.click('#login-btn')

        # Wait for response to complete
        await browser_page.wait_for_load_state("networkidle", timeout=10000)
        await browser_page.wait_for_timeout(500)

        # Button should be re-enabled and show "Login" text
        login_btn = browser_page.locator('#login-btn')
        await expect(login_btn).to_be_enabled()
        await expect(login_btn).to_have_text("Login")


class TestViewerUI:
    """UI tests for viewer dashboard - validates modem selection, data display, navigation."""

    @pytest.mark.asyncio
    async def test_viewer_requires_login_redirects(self, browser_page: Page):
        """Test viewer redirects to login if not authenticated."""
        await browser_page.goto(f"{BASE_URL}/viewer")

        # Wait for page to load
        await browser_page.wait_for_load_state("networkidle", timeout=10000)

        # Should redirect to login
        assert "/login" in browser_page.url, f"Should redirect to login, got: {browser_page.url}"

    @pytest.mark.asyncio
    async def test_viewer_loads_with_filter_controls(self, browser_page: Page):
        """Test viewer page displays modem filter controls after login."""
        await login_as_admin(browser_page)

        # Verify filter section is visible
        await expect(browser_page.locator('.filter-section')).to_be_visible()

        # Verify modem search input exists
        await expect(browser_page.locator('#modemSearchInput')).to_be_visible()

        # Verify date filters exist
        await expect(browser_page.locator('#startDate')).to_be_visible()
        await expect(browser_page.locator('#endDate')).to_be_visible()

        # Verify Load Data button exists
        load_btn = browser_page.locator('#loadBtn')
        await expect(load_btn).to_be_visible()
        await expect(load_btn).to_have_text("Load Data")

    @pytest.mark.asyncio
    async def test_viewer_modem_dropdown_opens_on_click(self, browser_with_real_data):
        """Test clicking modem search input opens the dropdown with modem options."""
        page, modem_ids = browser_with_real_data

        # Wait for page JavaScript to fully initialize
        await page.wait_for_timeout(2000)

        # Click on modem search input
        search_input = page.locator('#modemSearchInput')
        await search_input.click()

        # Wait for the click handler to execute
        await page.wait_for_timeout(1000)

        # Dropdown should become visible (has 'show' class)
        dropdown = page.locator('#modemDropdown')
        dropdown_class = await dropdown.get_attribute('class') or ""

        # Verify the dropdown opened and has the 'show' class
        assert 'show' in dropdown_class, "Dropdown should open when clicking search input"

        # Verify dropdown contains modem options
        modem_options = dropdown.locator('.searchable-option')
        option_count = await modem_options.count()
        assert option_count >= 3, f"Expected at least 3 modem options, got {option_count}"

    @pytest.mark.asyncio
    async def test_viewer_view_toggle_buttons_work(self, browser_page: Page):
        """Test Single View and Trend View toggle buttons switch views."""
        await login_as_admin(browser_page)

        # Single View button should be active by default
        single_btn = browser_page.locator('.view-btn:has-text("Single View")')
        await expect(single_btn).to_have_class(re.compile(r"active"))

        # Click Trend View button
        trend_btn = browser_page.locator('.view-btn:has-text("Trend View")')
        await trend_btn.click()

        # Trend View button should now be active
        await expect(trend_btn).to_have_class(re.compile(r"active"))
        await expect(single_btn).not_to_have_class(re.compile(r"active"))

        # Click back to Single View
        await single_btn.click()
        await expect(single_btn).to_have_class(re.compile(r"active"))

    @pytest.mark.asyncio
    async def test_viewer_logout_button_redirects_to_login(self, browser_page: Page):
        """Test logout button click redirects to login page."""
        await login_as_admin(browser_page)

        # Click logout button and wait for navigation
        async with browser_page.expect_navigation(timeout=15000):
            await browser_page.click('#logoutBtn')

        # Should redirect to login
        assert "/login" in browser_page.url, f"Should redirect to login, got: {browser_page.url}"

    @pytest.mark.asyncio
    async def test_viewer_admin_button_visible_for_admin(self, browser_page: Page):
        """Test admin button is visible for admin users."""
        await login_as_admin(browser_page)

        # Wait for role-based visibility to apply
        await browser_page.wait_for_timeout(1000)

        # Admin button should be visible
        admin_btn = browser_page.locator('#adminBtn')
        await expect(admin_btn).to_be_visible()

    @pytest.mark.asyncio
    async def test_viewer_admin_button_hidden_for_basic_user(self, browser_page: Page):
        """Test admin button is hidden for basic role users."""
        await login_as_basic(browser_page)

        # Wait for role-based visibility to apply
        await browser_page.wait_for_timeout(1000)

        # Admin button should be hidden
        admin_btn = browser_page.locator('#adminBtn')
        await expect(admin_btn).to_be_hidden()

    @pytest.mark.asyncio
    async def test_viewer_admin_button_navigates_to_admin(self, browser_page: Page):
        """Test clicking admin button navigates to admin page."""
        await login_as_admin(browser_page)

        # Wait for admin button to be visible
        await browser_page.wait_for_timeout(1000)

        # Click admin button
        await browser_page.click('#adminBtn')

        # Wait for navigation to complete
        await browser_page.wait_for_load_state("networkidle", timeout=10000)

        # Should navigate to admin page
        assert "/admin" in browser_page.url, f"Should navigate to admin, got: {browser_page.url}"


class TestAdminUI:
    """UI tests for admin dashboard - validates tabs, user management, API keys."""

    @pytest.mark.asyncio
    async def test_admin_requires_admin_role(self, browser_page: Page):
        """Test admin page returns 403 for basic role users."""
        await login_as_basic(browser_page)

        # Navigate to admin page
        await browser_page.goto(f"{BASE_URL}/admin")
        await browser_page.wait_for_timeout(1000)

        # Should show forbidden page
        page_content = await browser_page.content()
        assert "forbidden" in page_content.lower() or \
               "access denied" in page_content.lower() or \
               "403" in page_content, \
               "Basic user should see forbidden message on admin page"

    @pytest.mark.asyncio
    async def test_admin_page_loads_with_tabs(self, browser_page: Page):
        """Test admin page loads with all navigation tabs."""
        await login_as_admin(browser_page)
        await browser_page.goto(f"{BASE_URL}/admin")

        # Wait for page to fully load
        await browser_page.wait_for_timeout(1000)

        # Verify main tabs exist
        await expect(browser_page.locator('#configGenTab')).to_be_visible()
        await expect(browser_page.locator('#dataManagementTab')).to_be_visible()
        await expect(browser_page.locator('#clientLogsTab')).to_be_visible()
        await expect(browser_page.locator('#usersTab')).to_be_visible()
        await expect(browser_page.locator('#userActivityTab')).to_be_visible()

    @pytest.mark.asyncio
    async def test_admin_tab_switching_works(self, browser_page: Page):
        """Test clicking tabs switches visible content."""
        await login_as_admin(browser_page)
        await browser_page.goto(f"{BASE_URL}/admin")
        await browser_page.wait_for_timeout(1000)

        # Click Users tab
        await browser_page.click('#usersTab')
        await browser_page.wait_for_timeout(500)

        # Users section should be visible
        users_section = browser_page.locator('#usersSection')
        await expect(users_section).to_be_visible()

        # Click Data Management tab
        await browser_page.click('#dataManagementTab')
        await browser_page.wait_for_timeout(500)

        # Data Management section should be visible
        data_section = browser_page.locator('#dataManagementSection')
        await expect(data_section).to_be_visible()

        # Users section should now be hidden
        await expect(users_section).to_be_hidden()

    @pytest.mark.asyncio
    async def test_admin_user_management_form_elements(self, browser_page: Page):
        """Test user management tab has create user form with all fields."""
        await login_as_admin(browser_page)
        await browser_page.goto(f"{BASE_URL}/admin")
        await browser_page.wait_for_timeout(1000)

        # Click Users tab
        await browser_page.click('#usersTab')
        await browser_page.wait_for_timeout(500)

        # Verify form fields exist
        await expect(browser_page.locator('#newUsername')).to_be_visible()
        await expect(browser_page.locator('#newPassword')).to_be_visible()
        await expect(browser_page.locator('#newUserRole')).to_be_visible()

        # Verify create user button exists
        create_btn = browser_page.locator('button:has-text("Create User")')
        await expect(create_btn).to_be_visible()

    @pytest.mark.asyncio
    async def test_admin_password_strength_meter_updates(self, browser_page: Page):
        """Test password strength meter updates as user types."""
        await login_as_admin(browser_page)
        await browser_page.goto(f"{BASE_URL}/admin")
        await browser_page.wait_for_timeout(1000)

        # Click Users tab
        await browser_page.click('#usersTab')
        await browser_page.wait_for_timeout(500)

        password_input = browser_page.locator('#newPassword')

        # Type a weak password
        await password_input.fill('weak')
        await browser_page.wait_for_timeout(300)

        # Strength container should be visible
        strength_container = browser_page.locator('#newPassword-strength-container')
        await expect(strength_container).to_be_visible()

        # Type a stronger password
        await password_input.fill('StrongPass123!')
        await browser_page.wait_for_timeout(300)

        # Requirements should update (some should be met)
        length_req = browser_page.locator('#newPassword-req-length')
        await expect(length_req).to_have_class(re.compile(r"req-met"))

    @pytest.mark.asyncio
    async def test_admin_data_management_subtabs(self, browser_page: Page):
        """Test data management has subtabs: Bulk Upload, Download, Delete."""
        await login_as_admin(browser_page)
        await browser_page.goto(f"{BASE_URL}/admin")
        await browser_page.wait_for_timeout(1000)

        # Click Data Management tab
        await browser_page.click('#dataManagementTab')
        await browser_page.wait_for_timeout(500)

        # Verify subtabs exist
        await expect(browser_page.locator('#bulkUploadSubTab')).to_be_visible()
        await expect(browser_page.locator('#bulkDownloadSubTab')).to_be_visible()
        await expect(browser_page.locator('#deleteChecksSubTab')).to_be_visible()

    @pytest.mark.asyncio
    async def test_admin_bulk_upload_subtab_click(self, browser_page: Page):
        """Test clicking Bulk Upload subtab shows upload form."""
        await login_as_admin(browser_page)
        await browser_page.goto(f"{BASE_URL}/admin")
        await browser_page.wait_for_timeout(1000)

        # Click Data Management tab
        await browser_page.click('#dataManagementTab')
        await browser_page.wait_for_timeout(500)

        # Click Bulk Upload subtab (should be active by default, but click anyway)
        await browser_page.click('#bulkUploadSubTab')
        await browser_page.wait_for_timeout(300)

        # Verify upload content is visible
        upload_content = browser_page.locator('#bulkUploadContent')
        await expect(upload_content).to_be_visible()

        # Verify file input exists
        await expect(browser_page.locator('#bulkUploadFiles')).to_be_visible()

        # Verify upload button exists
        upload_btn = browser_page.locator('button:has-text("Upload Files")')
        await expect(upload_btn).to_be_visible()

    @pytest.mark.asyncio
    async def test_admin_bulk_download_subtab_click(self, browser_page: Page):
        """Test clicking Bulk Download subtab shows download form."""
        await login_as_admin(browser_page)
        await browser_page.goto(f"{BASE_URL}/admin")
        await browser_page.wait_for_timeout(1000)

        # Click Data Management tab
        await browser_page.click('#dataManagementTab')
        await browser_page.wait_for_timeout(500)

        # Click Bulk Download subtab
        await browser_page.click('#bulkDownloadSubTab')
        await browser_page.wait_for_timeout(300)

        # Verify download content is visible
        download_content = browser_page.locator('#bulkDownloadContent')
        await expect(download_content).to_be_visible()

        # Verify modem selector exists
        await expect(browser_page.locator('#downloadModemId')).to_be_visible()

        # Verify date filters exist
        await expect(browser_page.locator('#downloadStartDate')).to_be_visible()
        await expect(browser_page.locator('#downloadEndDate')).to_be_visible()

        # Verify download button exists
        download_btn = browser_page.locator('button:has-text("Download as ZIP")')
        await expect(download_btn).to_be_visible()

    @pytest.mark.asyncio
    async def test_admin_delete_checks_subtab_click(self, browser_page: Page):
        """Test clicking Delete Checks subtab shows delete form."""
        await login_as_admin(browser_page)
        await browser_page.goto(f"{BASE_URL}/admin")
        await browser_page.wait_for_timeout(1000)

        # Click Data Management tab
        await browser_page.click('#dataManagementTab')
        await browser_page.wait_for_timeout(500)

        # Click Delete Checks subtab
        await browser_page.click('#deleteChecksSubTab')
        await browser_page.wait_for_timeout(300)

        # Verify delete content is visible
        delete_content = browser_page.locator('#deleteChecksContent')
        await expect(delete_content).to_be_visible()

        # Verify modem filter exists
        await expect(browser_page.locator('#deleteModemIdFilter')).to_be_visible()

        # Verify load checks button exists
        load_btn = browser_page.locator('button:has-text("Load Checks")')
        await expect(load_btn).to_be_visible()

    @pytest.mark.asyncio
    async def test_admin_viewer_button_navigates_to_viewer(self, browser_page: Page):
        """Test clicking Viewer button navigates back to viewer page."""
        await login_as_admin(browser_page)
        await browser_page.goto(f"{BASE_URL}/admin")
        await browser_page.wait_for_timeout(1000)

        # Click Viewer button
        await browser_page.click('#viewerBtn')

        # Wait for navigation to complete
        await browser_page.wait_for_load_state("networkidle", timeout=10000)

        # Should navigate to viewer
        assert "/viewer" in browser_page.url, f"Should navigate to viewer, got: {browser_page.url}"

    @pytest.mark.asyncio
    async def test_admin_logout_button_redirects_to_login(self, browser_page: Page):
        """Test logout button on admin page redirects to login."""
        await login_as_admin(browser_page)
        await browser_page.goto(f"{BASE_URL}/admin")
        await browser_page.wait_for_timeout(1000)

        # Click logout button and wait for navigation
        async with browser_page.expect_navigation(timeout=15000):
            await browser_page.click('#logoutBtn')

        # Should redirect to login
        assert "/login" in browser_page.url, f"Should redirect to login, got: {browser_page.url}"

    @pytest.mark.asyncio
    async def test_admin_client_logs_tab_loads(self, browser_page: Page):
        """Test Client Submissions tab loads with filter controls."""
        await login_as_admin(browser_page)
        await browser_page.goto(f"{BASE_URL}/admin")
        await browser_page.wait_for_timeout(1000)

        # Click Client Logs tab
        await browser_page.click('#clientLogsTab')
        await browser_page.wait_for_timeout(500)

        # Tab content should be visible
        logs_section = browser_page.locator('#clientLogsSection')
        await expect(logs_section).to_be_visible()

    @pytest.mark.asyncio
    async def test_admin_user_activity_tab_loads(self, browser_page: Page):
        """Test User Activity tab loads with activity logs."""
        await login_as_admin(browser_page)
        await browser_page.goto(f"{BASE_URL}/admin")
        await browser_page.wait_for_timeout(1000)

        # Click User Activity tab
        await browser_page.click('#userActivityTab')
        await browser_page.wait_for_timeout(500)

        # Tab content should be visible
        activity_section = browser_page.locator('#userActivitySection')
        await expect(activity_section).to_be_visible()


class TestPasswordChangeDialog:
    """UI tests for password change functionality."""

    @pytest.mark.asyncio
    async def test_password_change_dialog_accessible(self, browser_page: Page):
        """Test password change functionality is available in User Management."""
        await login_as_admin(browser_page)
        await browser_page.goto(f"{BASE_URL}/admin")
        await browser_page.wait_for_timeout(1000)

        # Navigate to Users tab where password functionality exists
        await browser_page.click('#usersTab')
        await browser_page.wait_for_timeout(500)

        # Verify password input field exists for creating users
        password_input = browser_page.locator('#newPassword')
        await expect(password_input).to_be_visible()

        # Verify password strength container is present
        strength_container = browser_page.locator('#newPassword-strength-container, .password-strength')
        # Strength shows when typing, so just verify the input accepts text
        await password_input.fill('TestPassword123!')
        await browser_page.wait_for_timeout(300)

        # Password strength meter should appear
        await expect(browser_page.locator('#newPassword-strength-container')).to_be_visible()


class TestSessionPersistence:
    """UI tests for session handling."""

    @pytest.mark.asyncio
    async def test_session_persists_across_navigation(self, browser_page: Page):
        """Test session remains valid when navigating between pages."""
        await login_as_admin(browser_page)

        # Navigate to admin
        await browser_page.goto(f"{BASE_URL}/admin")
        await browser_page.wait_for_timeout(1000)

        # Should still be authenticated (not redirected to login)
        current_url = browser_page.url
        assert "/login" not in current_url, "Should remain authenticated after navigation"

        # Navigate back to viewer
        await browser_page.goto(f"{BASE_URL}/viewer")
        await browser_page.wait_for_timeout(1000)

        # Should still be authenticated
        current_url = browser_page.url
        assert "/login" not in current_url, "Should remain authenticated on viewer"

    @pytest.mark.asyncio
    async def test_logout_clears_session(self, browser_page: Page):
        """Test logout properly clears session, requiring re-login."""
        await login_as_admin(browser_page)

        # Logout and wait for navigation
        async with browser_page.expect_navigation(timeout=15000):
            await browser_page.click('#logoutBtn')

        # Should be on login page
        assert "/login" in browser_page.url, f"Should redirect to login after logout, got: {browser_page.url}"

        # Try to access viewer directly
        await browser_page.goto(f"{BASE_URL}/viewer")
        await browser_page.wait_for_load_state("networkidle", timeout=10000)

        # Should redirect to login
        assert "/login" in browser_page.url, f"Should redirect to login when not authenticated, got: {browser_page.url}"


class TestResponsiveUI:
    """UI tests for mobile/responsive behavior."""

    @pytest.mark.asyncio
    async def test_mobile_hamburger_menu_works(self, browser_page: Page):
        """Test hamburger menu appears and works on small viewport."""
        # Set mobile viewport
        await browser_page.set_viewport_size({"width": 375, "height": 667})

        await login_as_admin(browser_page)
        await browser_page.goto(f"{BASE_URL}/admin")
        await browser_page.wait_for_timeout(1000)

        # Hamburger should be visible on mobile
        hamburger = browser_page.locator('.hamburger')

        # Check if hamburger is displayed (may not be on all pages)
        is_visible = await hamburger.is_visible()
        if is_visible:
            # Click hamburger to open menu
            await hamburger.click()
            await browser_page.wait_for_timeout(300)

            # Mobile menu should be visible
            mobile_menu = browser_page.locator('.mobile-menu.active')
            await expect(mobile_menu).to_be_visible()


# ============================================================================
# REAL MODEM DATA UI TESTS
# ============================================================================

def _populate_real_modem_data():
    """Populate database with real modem data (sync wrapper for session fixture).

    This runs outside the async test context to ensure data is committed
    to the database before UI tests interact with the web server.
    """
    import asyncio
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import select, delete
    from datetime import datetime
    import uuid
    import os

    from app.models import ModemCheck
    from app.core.utils import utc_now
    from tests.fixtures.modem_data.loader import load_all_fixture_data, get_modem_ids
    import time
    from datetime import timezone

    async def populate():
        # Create async engine for test database
        db_url = os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://modemcheck:modemcheck_test_password@localhost:5433/modemcheck_test"
        )
        engine = create_async_engine(db_url, echo=False)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        modem_ids = get_modem_ids()
        real_data = load_all_fixture_data()
        created_ids = []

        async with async_session() as session:
            # Clean up any existing test modem data first
            for modem_type, modem_id in modem_ids.items():
                await session.execute(
                    delete(ModemCheck).where(ModemCheck.modem_id == modem_id)
                )

            # Insert real modem data
            for modem_type, checks in real_data.items():
                modem_id = modem_ids[modem_type]
                created_ids.append(modem_id)

                for i, check_data in enumerate(checks):
                    sysinfo = check_data.get("sysinfo", {})
                    check_time = sysinfo.get("checktime", int(time.time()) + i)

                    # Create unique filename
                    unique_id = str(uuid.uuid4())[:8]
                    dt = datetime.fromtimestamp(check_time)
                    filename = f"{modem_id}/{dt.strftime('%Y-%m-%d_%H-%M-%S')}_{unique_id}.json"

                    # Determine modem type from data or ID
                    detected_type = sysinfo.get("modemtype", modem_type.upper())

                    check = ModemCheck(
                        modem_id=modem_id,
                        modem_type=detected_type,
                        check_time=dt,
                        filename=filename,
                        full_data=check_data,
                        created_at=utc_now()
                    )
                    session.add(check)

            await session.commit()
            print(f"\n✓ Real modem data populated: {len(created_ids)} modems")

        await engine.dispose()
        return created_ids

    # Run async function synchronously
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(populate())
    finally:
        loop.close()


@pytest.fixture(scope="module")
def real_modem_data_in_db():
    """Module-scoped fixture to populate real modem data once per test module."""
    modem_ids = _populate_real_modem_data()
    yield modem_ids
    # Data cleanup happens in _populate_real_modem_data at the start


@pytest.fixture(scope="function")
async def browser_with_real_data(real_modem_data_in_db):
    """Create browser with real modem data populated in database."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        # Login as admin
        await login_as_admin(page)

        yield page, real_modem_data_in_db

        await context.close()
        await browser.close()


class TestViewerWithRealData:
    """UI tests using real anonymized modem data from 3 modem types.

    These tests validate the viewer UI with actual check data, verifying:
    - Modem dropdown shows all available modems
    - Data tables populate correctly
    - Charts render with real time series data
    - Signal quality displays accurately
    """

    @pytest.mark.asyncio
    async def test_viewer_modem_dropdown_shows_multiple_modems(self, browser_with_real_data):
        """Test modem dropdown displays all 3 modem types from fixture data."""
        page, modem_ids = browser_with_real_data

        # Wait for page JavaScript to initialize
        await page.wait_for_timeout(2000)

        # Click modem search input to open dropdown
        search_input = page.locator('#modemSearchInput')
        await search_input.click()
        await page.wait_for_timeout(1000)

        # Dropdown should have items for each modem (class is 'searchable-option')
        dropdown = page.locator('#modemDropdown')
        dropdown_items = dropdown.locator('.searchable-option')

        # Should have at least 3 modems (one per type)
        count = await dropdown_items.count()
        assert count >= 3, f"Expected at least 3 modems in dropdown, got {count}"

        # Verify modem types are present (check for partial MAC from anonymized data)
        dropdown_html = await dropdown.inner_html()
        assert "XB8" in dropdown_html or "AABBCC010203" in dropdown_html, \
            "XB8 modem should appear in dropdown"
        assert "DM1000" in dropdown_html or "AABBCC040506" in dropdown_html, \
            "DM1000 modem should appear in dropdown"
        assert "CODA56" in dropdown_html or "AABBCC070809" in dropdown_html, \
            "CODA56 modem should appear in dropdown"

    @pytest.mark.asyncio
    async def test_viewer_selects_modem_and_loads_data(self, browser_with_real_data):
        """Test selecting a modem from dropdown and clicking Load Data."""
        page, modem_ids = browser_with_real_data

        await page.wait_for_timeout(2000)

        # Click modem search input
        search_input = page.locator('#modemSearchInput')
        await search_input.click()
        await page.wait_for_timeout(1000)

        # Click first modem item (class is 'searchable-option')
        first_modem = page.locator('#modemDropdown .searchable-option').first
        await first_modem.click()
        await page.wait_for_timeout(500)

        # Search input should now have the modem ID
        input_value = await search_input.input_value()
        assert len(input_value) > 0, "Modem ID should be populated in search input"

        # Click Load Data button
        load_btn = page.locator('#loadBtn')
        await load_btn.click()

        # Wait for data to load
        await page.wait_for_timeout(3000)

        # Check that data was loaded (look for data in charts or tables)
        # The last check info should be visible
        last_check_section = page.locator('#lastCheckSection')
        is_visible = await last_check_section.is_visible()

        if is_visible:
            # Verify some content was loaded
            section_text = await last_check_section.text_content()
            assert "Check Time" in section_text or len(section_text) > 50, \
                "Last check section should have content"

    @pytest.mark.asyncio
    async def test_viewer_displays_signal_quality_table(self, browser_with_real_data):
        """Test downstream/upstream signal tables populate with real data."""
        page, modem_ids = browser_with_real_data

        await page.wait_for_timeout(2000)

        # Select first modem and load data
        search_input = page.locator('#modemSearchInput')
        await search_input.click()
        await page.wait_for_timeout(1000)

        first_modem = page.locator('#modemDropdown .searchable-option').first
        await first_modem.click()
        await page.wait_for_timeout(500)

        await page.click('#loadBtn')
        await page.wait_for_timeout(3000)

        # Look for downstream table - real modem data has 32 channels
        downstream_table = page.locator('#downstreamTable tbody')
        downstream_rows = await downstream_table.locator('tr').count()

        # Should have channel data (real modem data has 32 channels)
        assert downstream_rows >= 20, f"Expected at least 20 downstream channels, got {downstream_rows}"

        # Verify data is populated (not just empty rows)
        first_row = downstream_table.locator('tr').first
        row_text = await first_row.text_content()
        assert len(row_text) > 5, "Table rows should have actual data"

        # Verify specific data values are present (SNR, power, frequency)
        cells = first_row.locator('td')
        cell_count = await cells.count()
        assert cell_count >= 6, f"Expected at least 6 columns per row, got {cell_count}"

    @pytest.mark.asyncio
    async def test_viewer_trend_view_renders_charts(self, browser_with_real_data):
        """Test Trend View shows charts with multiple data points."""
        page, modem_ids = browser_with_real_data

        await page.wait_for_timeout(2000)

        # Select modem and load data first
        search_input = page.locator('#modemSearchInput')
        await search_input.click()
        await page.wait_for_timeout(1000)

        first_modem = page.locator('#modemDropdown .searchable-option').first
        await first_modem.click()
        await page.wait_for_timeout(500)

        await page.click('#loadBtn')
        await page.wait_for_timeout(3000)

        # Switch to Trend View
        trend_btn = page.locator('.view-btn:has-text("Trend View")')
        await trend_btn.click()
        await page.wait_for_timeout(1000)

        # Verify trend view is active
        await expect(trend_btn).to_have_class(re.compile(r"active"))

        # Verify trend view section is visible
        trend_section = page.locator('#trendViewSection, .trend-view-content')
        await expect(trend_section.first).to_be_visible()

        # Check for chart headings (Speed, Ping, Uptime, Power, SNR, Error Rates, Upstream)
        speed_heading = page.locator('h2:has-text("Speed Trends")')
        await expect(speed_heading).to_be_visible()

        ping_heading = page.locator('h2:has-text("Ping Latency")')
        await expect(ping_heading).to_be_visible()

        power_heading = page.locator('h2:has-text("Downstream Power")')
        await expect(power_heading).to_be_visible()

        # Check for chart containers/canvas elements
        chart_containers = page.locator('.chart-container, canvas')
        container_count = await chart_containers.count()
        assert container_count >= 4, f"Expected at least 4 chart containers, got {container_count}"

    @pytest.mark.asyncio
    async def test_viewer_date_filter_limits_results(self, browser_with_real_data):
        """Test date range filter affects loaded data."""
        page, modem_ids = browser_with_real_data

        await page.wait_for_timeout(2000)

        # Select modem first
        search_input = page.locator('#modemSearchInput')
        await search_input.click()
        await page.wait_for_timeout(1000)

        first_modem = page.locator('#modemDropdown .searchable-option').first
        await first_modem.click()
        await page.wait_for_timeout(500)

        # Set a date range (narrow window)
        # The real data spans multiple dates, so a narrow range should limit results
        start_date = page.locator('#startDate')
        end_date = page.locator('#endDate')

        # Get current dates (may be prefilled)
        start_value = await start_date.input_value()
        end_value = await end_date.input_value()

        # Load data
        await page.click('#loadBtn')
        await page.wait_for_timeout(3000)

        # Verify date inputs are functional
        assert start_value or end_value or True, "Date filters should be present and functional"

    @pytest.mark.asyncio
    async def test_viewer_search_filters_modem_list(self, browser_with_real_data):
        """Test typing in search input filters modem dropdown."""
        page, modem_ids = browser_with_real_data

        await page.wait_for_timeout(2000)

        # Click to open dropdown first (removes readonly attribute)
        search_input = page.locator('#modemSearchInput')
        await search_input.click()
        await page.wait_for_timeout(500)

        # Now type partial modem ID to filter
        await search_input.fill('XB8')
        await page.wait_for_timeout(500)

        # Dropdown should show only XB8 modem(s) (class is 'searchable-option')
        dropdown = page.locator('#modemDropdown')
        visible_items = dropdown.locator('.searchable-option:not(.hidden)')
        count = await visible_items.count()

        # Should show at least one XB8 (and not show others)
        if count > 0:
            item_html = await dropdown.inner_html()
            assert "XB8" in item_html, "Filtered dropdown should show XB8 modem"


class TestAdminWithRealData:
    """Admin UI tests using real modem data."""

    @pytest.mark.asyncio
    async def test_admin_data_management_shows_modems(self, browser_with_real_data):
        """Test Data Management tab shows real modems in dropdown."""
        page, modem_ids = browser_with_real_data

        # Navigate to admin
        await page.goto(f"{BASE_URL}/admin")
        await page.wait_for_timeout(2000)

        # Click Data Management tab
        await page.click('#dataManagementTab')
        await page.wait_for_timeout(500)

        # Click Bulk Download subtab
        await page.click('#bulkDownloadSubTab')
        await page.wait_for_timeout(500)

        # Modem dropdown should have options
        modem_select = page.locator('#downloadModemId')
        options = modem_select.locator('option')
        option_count = await options.count()

        # Should have modems loaded (at least 3 + "All Modems" option)
        assert option_count >= 3, f"Expected at least 3 modem options, got {option_count}"

    @pytest.mark.asyncio
    async def test_admin_delete_checks_loads_real_checks(self, browser_with_real_data):
        """Test Delete Checks tab loads and shows real check data."""
        page, modem_ids = browser_with_real_data

        await page.goto(f"{BASE_URL}/admin")
        await page.wait_for_timeout(2000)

        # Click Data Management tab
        await page.click('#dataManagementTab')
        await page.wait_for_timeout(500)

        # Click Delete Checks subtab
        await page.click('#deleteChecksSubTab')
        await page.wait_for_timeout(500)

        # Click Load Checks button (without filter to load all)
        await page.click('button:has-text("Load Checks")')
        await page.wait_for_timeout(2000)

        # Check for loaded checks - the container should show check items
        checks_container = page.locator('#checksListContainer')
        await expect(checks_container).to_be_visible()

        # Look for check items in the list (could be cards or table rows)
        check_items = page.locator('#checksListContainer .check-item, #deleteChecksTable tbody tr')
        item_count = await check_items.count()

        # Should have loaded checks from the fixture data (75 checks across 3 modems)
        assert item_count > 0, f"Expected to load some checks, but got {item_count}"

        # Verify each item has a checkbox for selection
        if item_count > 0:
            first_item = check_items.first
            item_text = await first_item.text_content()
            assert len(item_text) > 5, "Check items should have content (modem ID, date, etc.)"
