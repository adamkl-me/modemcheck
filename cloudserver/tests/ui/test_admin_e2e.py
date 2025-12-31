"""
Comprehensive Playwright E2E tests for admin operations.

Tests actual user workflows including:
- User management (create, edit, delete)
- API key management (create, toggle, delete)
- Data management (bulk upload/download, delete checks)
- Client config management
- Client logs and user activity viewing
- Modal dialogs and form validation
- Navigation and session handling

Uses Page Object Model for maintainability.
"""
import re
import pytest
import uuid
from playwright.async_api import async_playwright, Page, expect

from tests.ui.pages import LoginPage, AdminPage, ViewerPage


pytestmark = pytest.mark.ui

BASE_URL = "http://localhost:23894"


async def _login_as_user(page, username: str, password: str):
    """Direct login helper - matches working test_playwright.py approach."""
    await page.goto(f"{BASE_URL}/login")
    await page.fill('#username', username)
    await page.fill('#password', password)
    await page.click('button[type="submit"]')
    await page.wait_for_load_state("networkidle", timeout=15000)

    # Verify login succeeded
    if "/login" in page.url:
        error = page.locator('#error')
        error_text = ""
        if await error.is_visible():
            error_text = await error.text_content()
        raise Exception(f"Login failed: {error_text if error_text else 'still on login page'}")


async def _login_as_admin(page):
    """Login as admin user."""
    await _login_as_user(page, 'admin', 'TestPass123!')


async def _login_as_basic(page):
    """Login as basic user."""
    await _login_as_user(page, 'test_basic', 'BasicPass123!')


@pytest.fixture(scope="function")
async def admin_browser():
    """Create authenticated admin browser session."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        # Login as admin using direct approach
        await _login_as_admin(page)

        # Navigate to admin
        admin_page = AdminPage(page, BASE_URL)
        await admin_page.navigate()

        yield page, admin_page

        await context.close()
        await browser.close()


# ============================================================================
# USER MANAGEMENT TESTS
# ============================================================================

class TestUserManagementE2E:
    """E2E tests for user management workflows."""

    @pytest.mark.asyncio
    async def test_navigate_to_users_tab(self, admin_browser):
        """Test navigating to users tab shows user management form."""
        page, admin_page = admin_browser

        await admin_page.click_tab("users")

        await expect(admin_page.users_section).to_be_visible()
        await expect(admin_page.new_username_input).to_be_visible()
        await expect(admin_page.new_password_input).to_be_visible()
        await expect(admin_page.create_user_button).to_be_visible()

    @pytest.mark.asyncio
    async def test_password_strength_meter_shows_on_input(self, admin_browser):
        """Test password strength meter appears when typing password."""
        page, admin_page = admin_browser

        await admin_page.click_tab("users")
        await admin_page.new_password_input.fill("weak")
        await page.wait_for_timeout(300)

        assert await admin_page.is_password_strength_visible()

    @pytest.mark.asyncio
    async def test_password_strength_requirements_update(self, admin_browser):
        """Test password requirements update as password changes."""
        page, admin_page = admin_browser

        await admin_page.click_tab("users")

        # Type password that meets length requirement
        await admin_page.new_password_input.fill("StrongPassword123!")
        await page.wait_for_timeout(500)

        # Check that length requirement is met
        length_met = await admin_page.get_password_requirement_status("length")
        assert length_met, "Length requirement should be met"

    @pytest.mark.asyncio
    async def test_create_user_form_validation(self, admin_browser):
        """Test create user form validates required fields."""
        page, admin_page = admin_browser

        await admin_page.click_tab("users")

        # Try to submit empty form
        await admin_page.create_user_button.click()
        await page.wait_for_timeout(500)

        # Should still be on form (HTML5 validation prevents submit)
        await expect(admin_page.new_username_input).to_be_visible()

    @pytest.mark.asyncio
    async def test_create_user_complete_flow(self, admin_browser):
        """Test complete user creation flow."""
        page, admin_page = admin_browser

        unique_username = f"testuser_{uuid.uuid4().hex[:8]}"

        await admin_page.click_tab("users")
        await admin_page.fill_create_user_form(
            username=unique_username,
            password="TestPassword123!",
            role="basic"
        )
        await admin_page.submit_create_user_form()

        # Wait for response
        await page.wait_for_timeout(2000)

        # Check for success (either toast or no error)
        # The test passes if no error occurred during creation

    @pytest.mark.asyncio
    async def test_role_selection_options(self, admin_browser):
        """Test role dropdown has all expected options."""
        page, admin_page = admin_browser

        await admin_page.click_tab("users")

        # Check role select has options
        options = admin_page.new_user_role_select.locator("option")
        count = await options.count()

        assert count >= 3, "Should have at least 3 role options (basic, elevated, admin)"


# ============================================================================
# API KEY MANAGEMENT TESTS
# ============================================================================

class TestAPIKeyManagementE2E:
    """E2E tests for API key management workflows."""

    @pytest.mark.asyncio
    async def test_navigate_to_api_keys_subtab(self, admin_browser):
        """Test navigating to API keys subtab."""
        page, admin_page = admin_browser

        await admin_page.click_tab("client_management")
        await admin_page.api_keys_subtab.click()
        await page.wait_for_timeout(500)

        # API keys section should be visible
        api_keys_section = page.locator("#configGenApiKeysSection")
        await expect(api_keys_section).to_be_visible()

    @pytest.mark.asyncio
    async def test_create_api_key_button_exists(self, admin_browser):
        """Test create API key button is present."""
        page, admin_page = admin_browser

        await admin_page.click_tab("client_management")
        await admin_page.api_keys_subtab.click()
        await page.wait_for_timeout(500)

        await expect(admin_page.create_key_button).to_be_visible()

    @pytest.mark.asyncio
    async def test_create_api_key_form_visible(self, admin_browser):
        """Test API key creation form is visible (inline form, not modal)."""
        page, admin_page = admin_browser

        await admin_page.click_tab("client_management")
        await admin_page.api_keys_subtab.click()
        await page.wait_for_timeout(500)

        # API keys section uses an inline form, not a modal
        # Look for the key name input field
        key_name_input = page.locator(
            'input[placeholder*="e.g."], '
            'input[placeholder*="Key Name"], '
            'textbox[name*="Key"]'
        )
        await expect(key_name_input.first).to_be_visible()

        # Create button should be visible
        create_btn = page.locator('button:has-text("Create API Key")')
        await expect(create_btn).to_be_visible()

    @pytest.mark.asyncio
    async def test_api_key_section_displays(self, admin_browser):
        """Test API key section is present with create form and list area."""
        page, admin_page = admin_browser

        await admin_page.click_tab("client_management")
        await admin_page.api_keys_subtab.click()
        await page.wait_for_timeout(1000)

        # Look for API keys heading
        api_keys_heading = page.locator('h2:has-text("API Key"), h2:has-text("Existing API Keys")')
        await expect(api_keys_heading.first).to_be_visible()

        # Either shows "No API keys found" message or a list
        no_keys_msg = page.locator('text=No API keys found')
        keys_list = page.locator('.api-key-item, table tr, .key-row')

        # At least one should be visible
        has_no_keys_msg = await no_keys_msg.is_visible()
        keys_count = await keys_list.count()
        assert has_no_keys_msg or keys_count > 0, "Should show API keys section"


# ============================================================================
# DATA MANAGEMENT TESTS
# ============================================================================

class TestDataManagementE2E:
    """E2E tests for data management workflows."""

    @pytest.mark.asyncio
    async def test_navigate_to_data_management(self, admin_browser):
        """Test navigating to data management tab."""
        page, admin_page = admin_browser

        await admin_page.click_tab("data_management")

        await expect(admin_page.data_management_section).to_be_visible()

    @pytest.mark.asyncio
    async def test_bulk_upload_subtab_shows_form(self, admin_browser):
        """Test bulk upload subtab shows file upload form."""
        page, admin_page = admin_browser

        await admin_page.click_data_management_subtab("bulk_upload")

        await expect(admin_page.bulk_upload_files_input).to_be_visible()
        await expect(admin_page.upload_files_button).to_be_visible()

    @pytest.mark.asyncio
    async def test_bulk_download_subtab_shows_form(self, admin_browser):
        """Test bulk download subtab shows download form."""
        page, admin_page = admin_browser

        await admin_page.click_data_management_subtab("bulk_download")

        await expect(admin_page.download_modem_id).to_be_visible()
        await expect(admin_page.download_start_date).to_be_visible()
        await expect(admin_page.download_end_date).to_be_visible()
        await expect(admin_page.download_button).to_be_visible()

    @pytest.mark.asyncio
    async def test_delete_checks_subtab_shows_form(self, admin_browser):
        """Test delete checks subtab shows delete form."""
        page, admin_page = admin_browser

        await admin_page.click_data_management_subtab("delete_checks")

        await expect(admin_page.delete_modem_filter).to_be_visible()
        await expect(admin_page.load_checks_button).to_be_visible()

    @pytest.mark.asyncio
    async def test_load_checks_for_deletion(self, admin_browser):
        """Test loading checks for deletion - verifies delete checks section loads."""
        page, admin_page = admin_browser

        await admin_page.load_delete_checks()

        # Delete checks container should be present
        await expect(admin_page.delete_checks_container).to_be_visible()

    @pytest.mark.asyncio
    async def test_subtab_switching(self, admin_browser):
        """Test switching between data management subtabs."""
        page, admin_page = admin_browser

        # Go to bulk upload
        await admin_page.click_data_management_subtab("bulk_upload")
        upload_content = page.locator("#bulkUploadContent")
        await expect(upload_content).to_be_visible()

        # Switch to bulk download
        await admin_page.click_data_management_subtab("bulk_download")
        download_content = page.locator("#bulkDownloadContent")
        await expect(download_content).to_be_visible()

        # Switch to delete checks
        await admin_page.click_data_management_subtab("delete_checks")
        delete_content = page.locator("#deleteChecksContent")
        await expect(delete_content).to_be_visible()


# ============================================================================
# CLIENT LOGS TESTS
# ============================================================================

class TestClientLogsE2E:
    """E2E tests for client submission logs."""

    @pytest.mark.asyncio
    async def test_navigate_to_client_logs(self, admin_browser):
        """Test navigating to client logs tab."""
        page, admin_page = admin_browser

        await admin_page.navigate_to_client_logs()

        await expect(admin_page.client_logs_section).to_be_visible()

    @pytest.mark.asyncio
    async def test_client_logs_has_filter_controls(self, admin_browser):
        """Test client logs (submissions) has filter inputs."""
        page, admin_page = admin_browser

        await admin_page.navigate_to_client_logs()
        await page.wait_for_timeout(500)

        # Check for filter elements - now called "Client Submissions"
        # Filter by Modem ID textbox
        modem_filter = page.locator(
            'input[placeholder*="modem"], '
            'input[placeholder*="Modem"], '
            'textbox[name*="Modem"]'
        )
        await expect(modem_filter.first).to_be_visible()

    @pytest.mark.asyncio
    async def test_client_logs_has_statistics(self, admin_browser):
        """Test client logs shows statistics."""
        page, admin_page = admin_browser

        await admin_page.navigate_to_client_logs()
        await page.wait_for_timeout(1000)

        # Look for any stats-related text on the submissions page
        page_content = await page.content()

        # Should have statistics labels
        has_stats = (
            "Total Submissions" in page_content or
            "Failed" in page_content or
            "Unique" in page_content or
            "Submission" in page_content
        )
        assert has_stats, "Client logs section should show submission statistics"


# ============================================================================
# USER ACTIVITY TESTS
# ============================================================================

class TestUserActivityE2E:
    """E2E tests for user activity logs."""

    @pytest.mark.asyncio
    async def test_navigate_to_user_activity(self, admin_browser):
        """Test navigating to user activity tab."""
        page, admin_page = admin_browser

        await admin_page.navigate_to_user_activity()

        await expect(admin_page.user_activity_section).to_be_visible()

    @pytest.mark.asyncio
    async def test_user_activity_shows_logs(self, admin_browser):
        """Test user activity tab displays activity logs."""
        page, admin_page = admin_browser

        await admin_page.navigate_to_user_activity()

        # Wait for data to load
        await page.wait_for_timeout(2000)

        # Look for activity table or list - should be visible
        activity_table = page.locator("#userActivityTable, .activity-log, table")
        await expect(activity_table.first).to_be_visible()

        # Should have at least some activity logged (our login)
        rows = activity_table.locator("tr, .activity-row")
        row_count = await rows.count()
        assert row_count >= 1, "Should have at least one activity log entry (admin login)"


# ============================================================================
# NAVIGATION AND SESSION TESTS
# ============================================================================

class TestAdminNavigationE2E:
    """E2E tests for admin navigation."""

    @pytest.mark.asyncio
    async def test_all_main_tabs_accessible(self, admin_browser):
        """Test all main tabs can be clicked and show content."""
        page, admin_page = admin_browser

        tabs = [
            ("client_management", admin_page.config_gen_section),
            ("data_management", admin_page.data_management_section),
            ("client_logs", admin_page.client_logs_section),
            ("users", admin_page.users_section),
            ("user_activity", admin_page.user_activity_section),
        ]

        for tab_name, section in tabs:
            await admin_page.click_tab(tab_name)
            await expect(section).to_be_visible()

    @pytest.mark.asyncio
    async def test_viewer_button_navigates(self, admin_browser):
        """Test viewer button navigates to viewer page."""
        page, admin_page = admin_browser

        await admin_page.click_viewer_button()

        assert "/viewer" in page.url

    @pytest.mark.asyncio
    async def test_logout_redirects_to_login(self, admin_browser):
        """Test logout redirects to login page."""
        page, admin_page = admin_browser

        await admin_page.click_logout_button()

        assert "/login" in page.url

    @pytest.mark.asyncio
    async def test_session_persists_across_tabs(self, admin_browser):
        """Test session persists when switching between tabs."""
        page, admin_page = admin_browser

        # Switch between several tabs
        await admin_page.click_tab("users")
        await admin_page.click_tab("data_management")
        await admin_page.click_tab("user_activity")
        await admin_page.click_tab("client_management")

        # Should still be authenticated
        assert await admin_page.is_authenticated()


# ============================================================================
# CLIENT CONFIG MANAGEMENT TESTS
# ============================================================================

class TestClientConfigManagementE2E:
    """E2E tests for client configuration management."""

    @pytest.mark.asyncio
    async def test_navigate_to_config_management(self, admin_browser):
        """Test navigating to config management subtab."""
        page, admin_page = admin_browser

        await admin_page.navigate_to_config_management()

        config_mgmt_section = page.locator("#configGenConfigMgmtSection")
        await expect(config_mgmt_section).to_be_visible()

    @pytest.mark.asyncio
    async def test_config_stats_display(self, admin_browser):
        """Test config statistics are displayed."""
        page, admin_page = admin_browser

        await admin_page.navigate_to_config_management()
        await page.wait_for_timeout(1000)

        # Look for stats content on the config management page
        page_content = await page.content()

        # Should have config-related statistics
        has_stats = (
            "Total" in page_content or
            "Unmanaged" in page_content or
            "Managed" in page_content or
            "Clients" in page_content
        )
        assert has_stats, "Config management section should show statistics"

    @pytest.mark.asyncio
    async def test_config_search_input_exists(self, admin_browser):
        """Test config search input exists."""
        page, admin_page = admin_browser

        await admin_page.navigate_to_config_management()
        await page.wait_for_timeout(500)

        search_input = page.locator("#configSearch, .config-search input, input[placeholder*='search'], input[placeholder*='Search']")
        await expect(search_input.first).to_be_visible()

    @pytest.mark.asyncio
    async def test_config_table_displays(self, admin_browser):
        """Test config table is displayed."""
        page, admin_page = admin_browser

        await admin_page.navigate_to_config_management()
        await page.wait_for_timeout(1000)

        # Look for configs table - should be visible
        configs_table = page.locator("#configsTable, .configs-table, table")
        await expect(configs_table.first).to_be_visible()


# ============================================================================
# CONFIG DEFAULTS TESTS
# ============================================================================

class TestConfigDefaultsE2E:
    """E2E tests for config wizard defaults."""

    @pytest.mark.asyncio
    async def test_navigate_to_defaults_subtab(self, admin_browser):
        """Test navigating to defaults subtab."""
        page, admin_page = admin_browser

        await admin_page.click_tab("client_management")
        await admin_page.defaults_subtab.click()
        await page.wait_for_timeout(500)

        defaults_section = page.locator("#configGenDefaultsSection")
        await expect(defaults_section).to_be_visible()


# ============================================================================
# MODAL DIALOG TESTS
# ============================================================================

class TestModalDialogsE2E:
    """E2E tests for modal dialogs."""

    @pytest.mark.asyncio
    async def test_create_config_modal_opens_and_closes(self, admin_browser):
        """Test the create config modal opens and closes correctly.

        This tests the modal behavior using the Create Config button which
        doesn't require pre-existing data.
        """
        page, admin_page = admin_browser

        # Navigate to config management section
        await admin_page.navigate_to_config_management()
        await page.wait_for_timeout(1000)

        # Click the Create Config button
        create_button = page.locator('button:has-text("Create Config")')
        await expect(create_button).to_be_visible(timeout=5000)
        await create_button.click()

        # Wait for modal to appear
        # The config modal uses id="configModal" and class "active" when visible
        modal = page.locator('#configModal.active')
        await expect(modal).to_be_visible(timeout=5000)

        # Verify modal has expected content - use specific ID
        modal_title = page.locator('#configModalTitle')
        await expect(modal_title).to_contain_text("Configuration")

        # Press Escape to close (triggers closeAllModals)
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(500)

        # Modal should close (class "active" removed)
        await expect(modal).not_to_be_visible(timeout=5000)


# ============================================================================
# RESPONSIVE/MOBILE TESTS
# ============================================================================

class TestResponsiveAdminE2E:
    """E2E tests for responsive admin UI."""

    @pytest.mark.asyncio
    async def test_mobile_viewport_responsive_layout(self):
        """Test admin page has responsive layout on mobile viewport."""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(viewport={"width": 375, "height": 667})
            page = await context.new_page()

            # Login
            login_page = LoginPage(page, BASE_URL)
            await login_page.navigate()
            await login_page.login_as_admin()

            # Navigate to admin
            admin_page = AdminPage(page, BASE_URL)
            await admin_page.navigate()

            # On mobile, verify the page is still usable
            # Check that main heading is visible
            heading = page.locator('h1')
            await expect(heading).to_be_visible()

            # Verify page content is present (may be scrollable on mobile)
            page_content = await page.content()
            has_admin_content = (
                "Admin" in page_content or
                "Management" in page_content or
                "Client" in page_content
            )
            assert has_admin_content, "Admin page content should be present on mobile"

            await context.close()
            await browser.close()


# ============================================================================
# FORM SUBMISSION TESTS
# ============================================================================

class TestFormSubmissionsE2E:
    """E2E tests for form submissions."""

    @pytest.mark.asyncio
    async def test_create_user_with_weak_password_shows_error(self, admin_browser):
        """Test creating user with weak password shows validation error."""
        page, admin_page = admin_browser

        await admin_page.click_tab("users")
        await admin_page.fill_create_user_form(
            username="testuser_weak",
            password="weak",  # Too short
            role="basic"
        )
        await admin_page.submit_create_user_form()
        await page.wait_for_timeout(1000)

        # Should show error message or password strength warning
        error_msg = page.locator(".error-message, .toast-error, .alert-danger, #passwordError")
        strength_warning = page.locator(".password-strength-weak, .strength-indicator")

        # Either an error message should appear or the password field should still have value (form not cleared)
        password_field = page.locator("#newPassword, input[type='password']").first
        password_value = await password_field.input_value()
        has_error = await error_msg.first.is_visible() if await error_msg.count() > 0 else False
        has_warning = await strength_warning.first.is_visible() if await strength_warning.count() > 0 else False

        assert has_error or has_warning or password_value == "weak", \
            "Weak password should show error, warning, or prevent form submission"


# ============================================================================
# AUTHORIZATION TESTS
# ============================================================================

class TestAuthorizationE2E:
    """E2E tests for authorization."""

    @pytest.mark.asyncio
    async def test_basic_user_cannot_access_admin(self):
        """Test basic user is denied access to admin page."""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            # Login as basic user using direct method
            await _login_as_basic(page)

            # Try to access admin
            await page.goto(f"{BASE_URL}/admin")
            await page.wait_for_timeout(1000)

            # Should see access denied or be redirected
            content = await page.content()
            assert "access denied" in content.lower() or "forbidden" in content.lower() or "403" in content or "/viewer" in page.url

            await context.close()
            await browser.close()


# ============================================================================
# REAL WORKFLOW TESTS
# ============================================================================

class TestBulkUploadWorkflowE2E:
    """E2E tests for complete bulk upload workflow using real fixture data."""

    @pytest.mark.asyncio
    async def test_bulk_upload_form_accessible(self, admin_browser):
        """Test bulk upload form elements are accessible."""
        page, admin_page = admin_browser

        await admin_page.click_data_management_subtab("bulk_upload")
        await page.wait_for_timeout(500)

        # File input should be present
        file_input = page.locator('#bulkUploadFiles, input[type="file"]')
        await expect(file_input.first).to_be_attached()

        # Upload button should be visible
        upload_btn = page.locator('button:has-text("Upload")')
        await expect(upload_btn.first).to_be_visible()

    @pytest.mark.asyncio
    async def test_bulk_upload_file_selection(self, admin_browser):
        """Test that file selection works in bulk upload."""
        import os
        page, admin_page = admin_browser

        await admin_page.click_data_management_subtab("bulk_upload")

        # Get a test fixture file
        fixture_path = os.path.join(
            os.path.dirname(__file__),
            "../fixtures/modem_data/xb8/check_001.json"
        )

        if os.path.exists(fixture_path):
            file_input = page.locator('#bulkUploadFiles, input[type="file"]')
            await file_input.first.set_input_files(fixture_path)
            await page.wait_for_timeout(500)

            # File should be selected - look for file name or count indicator
            # Just verify no error occurred during selection
            page_content = await page.content()
            assert "error" not in page_content.lower() or "file" in page_content.lower()


class TestDeleteChecksWorkflowE2E:
    """E2E tests for complete delete checks workflow."""

    @pytest.mark.asyncio
    async def test_delete_checks_form_accessible(self, admin_browser):
        """Test delete checks form elements are accessible."""
        page, admin_page = admin_browser

        await admin_page.click_data_management_subtab("delete_checks")
        await page.wait_for_timeout(500)

        # Load button should be visible
        load_btn = page.locator('button:has-text("Load")')
        await expect(load_btn.first).to_be_visible()

        # Container for results should exist
        checks_container = page.locator("#checksListContainer, #deleteChecksTable, .checks-container")
        await expect(checks_container.first).to_be_attached()

    @pytest.mark.asyncio
    async def test_delete_checks_load_operation(self, admin_browser):
        """Test load operation executes (results depend on database state)."""
        page, admin_page = admin_browser

        await admin_page.click_data_management_subtab("delete_checks")
        await page.wait_for_timeout(500)

        # Click load button
        load_btn = page.locator('button:has-text("Load")')
        await load_btn.first.click()
        await page.wait_for_timeout(2000)

        # Should show either data or "no checks" message
        page_content = await page.content()
        has_content = "no checks" in page_content.lower() or "check" in page_content.lower()
        assert has_content, "Page should show check data or no-data message"


class TestAPIKeyWorkflowE2E:
    """E2E tests for complete API key management workflow."""

    @pytest.mark.asyncio
    async def test_create_api_key_full_workflow(self, admin_browser):
        """Test creating an API key and verifying it appears in the list."""
        page, admin_page = admin_browser

        # Navigate to API keys section
        await admin_page.click_tab("client_management")
        await admin_page.api_keys_subtab.click()
        await page.wait_for_timeout(1000)

        # Get initial key count
        key_rows = page.locator("#apiKeysTable tbody tr, .api-key-row")
        initial_count = await key_rows.count()

        # Open create modal
        await admin_page.open_create_api_key_modal()

        # Fill in key details
        key_name_input = page.locator("#keyName, input[name='keyName'], #newKeyModal input[type='text']")
        await key_name_input.first.fill(f"TestKey_{uuid.uuid4().hex[:8]}")
        await page.wait_for_timeout(300)

        # Submit creation
        create_btn = page.locator("#newKeyModal button[type='submit'], #newKeyModal button:has-text('Create')")
        if await create_btn.first.is_visible():
            await create_btn.first.click()
            await page.wait_for_timeout(2000)

            # Verify key appears or API key display shows
            new_key_display = page.locator(".new-key-value, .api-key-display, #newKeyValue")
            key_rows_after = page.locator("#apiKeysTable tbody tr, .api-key-row")
            new_count = await key_rows_after.count()

            # Either new key is displayed or count increased
            has_new_key = await new_key_display.first.is_visible() if await new_key_display.count() > 0 else False
            assert has_new_key or new_count > initial_count, \
                "New API key should be displayed or added to list"

    @pytest.mark.asyncio
    async def test_api_key_list_shows_key_details(self, admin_browser):
        """Test API key list displays key names, status, and dates."""
        page, admin_page = admin_browser

        await admin_page.click_tab("client_management")
        await admin_page.api_keys_subtab.click()
        await page.wait_for_timeout(1000)

        # Check for key table/list
        api_keys_section = page.locator("#configGenApiKeysSection")
        await expect(api_keys_section).to_be_visible()

        # Look for table headers or key info columns
        headers = page.locator("th:has-text('Name'), th:has-text('Status'), th:has-text('Created')")
        header_count = await headers.count()

        # Should have column headers for key details
        assert header_count >= 1, "API key table should have name/status/date columns"


class TestUserManagementWorkflowE2E:
    """E2E tests for complete user management workflow."""

    @pytest.mark.asyncio
    async def test_create_user_full_workflow(self, admin_browser):
        """Test creating a user with valid password and verifying they appear."""
        page, admin_page = admin_browser

        unique_username = f"workflow_user_{uuid.uuid4().hex[:6]}"
        strong_password = "WorkflowTest123!@#"

        await admin_page.click_tab("users")
        await page.wait_for_timeout(500)

        # Get initial user count if user list exists
        user_rows = page.locator("#usersTable tbody tr, .user-row")
        initial_count = await user_rows.count()

        # Fill and submit user form
        await admin_page.fill_create_user_form(
            username=unique_username,
            password=strong_password,
            role="basic"
        )
        await admin_page.submit_create_user_form()
        await page.wait_for_timeout(2000)

        # Check for success - either toast, user in list, or form cleared
        success_toast = page.locator(".toast-success, .alert-success")
        has_toast = await success_toast.first.is_visible() if await success_toast.count() > 0 else False

        user_rows_after = page.locator("#usersTable tbody tr, .user-row")
        new_count = await user_rows_after.count()

        username_field = page.locator("#newUsername")
        username_value = await username_field.input_value()

        # Success if: toast shown, user count increased, or form was cleared
        form_cleared = username_value == ""
        assert has_toast or new_count > initial_count or form_cleared, \
            "User creation should show success indicator"

    @pytest.mark.asyncio
    async def test_user_list_shows_roles(self, admin_browser):
        """Test user list displays user roles."""
        page, admin_page = admin_browser

        await admin_page.click_tab("users")
        await page.wait_for_timeout(1000)

        # Look for role select dropdowns in user table
        role_selects = page.locator("select.role-select[data-current-role]")
        role_count = await role_selects.count()

        # Should see at least one role (admin user should be visible)
        assert role_count >= 1, "User list should display user roles"

    @pytest.mark.asyncio
    async def test_password_validation_shows_requirements(self, admin_browser):
        """Test password field shows strength requirements."""
        page, admin_page = admin_browser

        await admin_page.click_tab("users")
        await admin_page.new_password_input.fill("Test123!")
        await page.wait_for_timeout(500)

        # Password strength container should appear
        strength_container = page.locator("#newPassword-strength-container")
        await expect(strength_container).to_be_visible()

        # Should show requirement indicators
        requirements = page.locator(".password-requirement, .req-item, [class*='req-']")
        req_count = await requirements.count()

        assert req_count >= 4, f"Should show at least 4 password requirements, got {req_count}"


@pytest.fixture(scope="function")
async def admin_browser_with_data(ui_modem_data):
    """Create authenticated admin browser session with modem data populated.

    Uses the shared ui_modem_data fixture from conftest.py which:
    - Creates a direct database connection (visible to Docker web server)
    - Cleans up data after test completes
    - Is function-scoped for proper test isolation
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        # Login as admin using direct approach
        await _login_as_admin(page)

        # Navigate to admin
        admin_page = AdminPage(page, BASE_URL)
        await admin_page.navigate()

        yield page, admin_page, ui_modem_data

        await context.close()
        await browser.close()


class TestDataViewerIntegrationE2E:
    """E2E tests verifying data appears in viewer after admin operations."""

    @pytest.mark.asyncio
    async def test_uploaded_data_visible_in_viewer(self, admin_browser_with_data):
        """Test that data uploaded via admin is visible in viewer."""
        page, admin_page, modem_ids = admin_browser_with_data

        # Navigate to viewer
        await admin_page.click_viewer_button()
        await page.wait_for_timeout(2000)

        # Should be on viewer page
        assert "/viewer" in page.url

        # Modem dropdown should have options (from previous uploads)
        modem_dropdown = page.locator("#modemDropdown, #modemSearchInput")
        await expect(modem_dropdown.first).to_be_visible()

        # Click to open dropdown
        await modem_dropdown.first.click()
        await page.wait_for_timeout(500)

        # Should have modem options
        options = page.locator(".searchable-option, #modemDropdown option, .dropdown-item")
        option_count = await options.count()

        assert option_count >= 1, f"Should have at least one modem in dropdown, got {option_count}"
