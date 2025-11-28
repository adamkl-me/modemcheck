"""Admin page object for Playwright tests."""
from playwright.async_api import Page, expect
from typing import Optional, Dict, Any


class AdminPage:
    """Page object for the admin dashboard."""

    URL = "/admin"

    def __init__(self, page: Page, base_url: str = "http://localhost:23894"):
        self.page = page
        self.base_url = base_url

        # Header buttons
        self.viewer_button = page.locator("#viewerBtn")
        self.logout_button = page.locator("#logoutBtn")
        self.hamburger = page.locator(".hamburger")

        # Main tabs
        self.client_management_tab = page.locator("#configGenTab")
        self.data_management_tab = page.locator("#dataManagementTab")
        self.client_logs_tab = page.locator("#clientLogsTab")
        self.users_tab = page.locator("#usersTab")
        self.user_activity_tab = page.locator("#userActivityTab")

        # Tab sections
        self.config_gen_section = page.locator("#configGenSection")
        self.data_management_section = page.locator("#dataManagementSection")
        self.client_logs_section = page.locator("#clientLogsSection")
        self.users_section = page.locator("#usersSection")
        self.user_activity_section = page.locator("#userActivitySection")

        # Client Management sub-tabs
        self.config_mgmt_subtab = page.locator("#configGenConfigMgmtSubTab")
        self.api_keys_subtab = page.locator("#configGenApiKeysSubTab")
        self.defaults_subtab = page.locator("#configGenDefaultsSubTab")

        # Data Management sub-tabs
        self.bulk_upload_subtab = page.locator("#bulkUploadSubTab")
        self.bulk_download_subtab = page.locator("#bulkDownloadSubTab")
        self.delete_checks_subtab = page.locator("#deleteChecksSubTab")

        # Users section form elements
        self.new_username_input = page.locator("#newUsername")
        self.new_password_input = page.locator("#newPassword")
        self.new_user_role_select = page.locator("#newUserRole")
        self.create_user_button = page.locator('button:has-text("Create User")')
        self.password_strength_container = page.locator("#newPassword-strength-container")

        # API Keys section
        self.create_key_button = page.locator('button[onclick="createKey()"]')
        self.new_key_modal = page.locator("#newKeyModal")
        self.edit_key_modal = page.locator("#editKeyModal")

        # Bulk Upload section
        self.bulk_upload_files_input = page.locator("#bulkUploadFiles")
        self.upload_files_button = page.locator('button:has-text("Upload Files")')

        # Bulk Download section
        self.download_modem_id = page.locator("#downloadModemId")
        self.download_start_date = page.locator("#downloadStartDate")
        self.download_end_date = page.locator("#downloadEndDate")
        self.download_button = page.locator('button:has-text("Download as ZIP")')

        # Delete Checks section
        self.delete_modem_filter = page.locator("#deleteModemIdFilter")
        self.load_checks_button = page.locator('button[onclick="loadChecksForDeletion()"]')
        self.delete_checks_container = page.locator("#checksListContainer")

    async def navigate(self):
        """Navigate to admin page."""
        await self.page.goto(f"{self.base_url}{self.URL}")
        await self.page.wait_for_load_state("networkidle")
        await self.page.wait_for_timeout(1000)  # Wait for JS init

    async def is_admin_page(self) -> bool:
        """Check if currently on admin page."""
        return "/admin" in self.page.url

    async def is_authenticated(self) -> bool:
        """Check if page shows authenticated state."""
        container = self.page.locator(".container.authenticated")
        return await container.is_visible()

    # Navigation methods
    async def click_tab(self, tab_name: str):
        """Click a main tab by name."""
        tab_map = {
            "client_management": self.client_management_tab,
            "data_management": self.data_management_tab,
            "client_logs": self.client_logs_tab,
            "users": self.users_tab,
            "user_activity": self.user_activity_tab,
        }
        if tab_name in tab_map:
            await tab_map[tab_name].click()
            await self.page.wait_for_timeout(500)

    async def click_viewer_button(self):
        """Click viewer button to navigate back."""
        await self.viewer_button.click()
        await self.page.wait_for_load_state("networkidle")

    async def click_logout_button(self):
        """Click logout button."""
        async with self.page.expect_navigation(timeout=15000):
            await self.logout_button.click()

    # User Management methods
    async def fill_create_user_form(
        self,
        username: str,
        password: str,
        role: str = "basic"
    ):
        """Fill out the create user form."""
        await self.new_username_input.fill(username)
        await self.new_password_input.fill(password)
        await self.new_user_role_select.select_option(role)

    async def submit_create_user_form(self):
        """Click the create user button."""
        await self.create_user_button.click()
        await self.page.wait_for_timeout(1000)

    async def create_user(
        self,
        username: str,
        password: str,
        role: str = "basic"
    ):
        """Create a new user."""
        await self.click_tab("users")
        await self.fill_create_user_form(username, password, role)
        await self.submit_create_user_form()

    async def is_password_strength_visible(self) -> bool:
        """Check if password strength meter is visible."""
        return await self.password_strength_container.is_visible()

    async def get_password_requirement_status(self, requirement: str) -> bool:
        """Check if a password requirement is met."""
        req_locator = self.page.locator(f"#newPassword-req-{requirement}")
        class_attr = await req_locator.get_attribute("class") or ""
        return "req-met" in class_attr

    # Data Management methods
    async def click_data_management_subtab(self, subtab: str):
        """Click a data management subtab."""
        await self.click_tab("data_management")
        subtab_map = {
            "bulk_upload": self.bulk_upload_subtab,
            "bulk_download": self.bulk_download_subtab,
            "delete_checks": self.delete_checks_subtab,
        }
        if subtab in subtab_map:
            await subtab_map[subtab].click()
            await self.page.wait_for_timeout(300)

    async def load_delete_checks(self, modem_filter: Optional[str] = None):
        """Load checks for deletion."""
        await self.click_data_management_subtab("delete_checks")
        if modem_filter:
            await self.delete_modem_filter.fill(modem_filter)
        await self.load_checks_button.click()
        await self.page.wait_for_timeout(2000)

    async def get_delete_checks_item_count(self) -> int:
        """Get number of check items in delete checks container."""
        items = self.delete_checks_container.locator(".check-item")
        return await items.count()

    # API Keys methods
    async def open_create_api_key_modal(self):
        """Open the create API key modal."""
        await self.click_tab("client_management")
        await self.api_keys_subtab.click()
        await self.page.wait_for_timeout(500)
        await self.create_key_button.click()
        await self.page.wait_for_timeout(500)

    async def is_new_key_modal_visible(self) -> bool:
        """Check if new key modal is visible."""
        return await self.new_key_modal.is_visible()

    async def close_modal(self):
        """Close any open modal by clicking backdrop or X."""
        # Try clicking outside the modal (backdrop)
        backdrop = self.page.locator(".modal.active")
        if await backdrop.is_visible():
            await self.page.keyboard.press("Escape")
            await self.page.wait_for_timeout(300)

    # Client Config Management methods
    async def navigate_to_config_management(self):
        """Navigate to client config management subtab."""
        await self.click_tab("client_management")
        await self.config_mgmt_subtab.click()
        await self.page.wait_for_timeout(500)

    async def get_config_stats(self) -> Dict[str, int]:
        """Get config statistics from the dashboard."""
        stats = {}
        stat_labels = ["Total", "Unmanaged", "OneTime-Ready", "OneTime-Active",
                       "Enforced-Ready", "Enforced-Active", "Awaiting", "Stale"]
        for label in stat_labels:
            stat = self.page.locator(f".stat-item:has-text('{label}') .stat-value")
            if await stat.is_visible():
                text = await stat.text_content()
                stats[label] = int(text) if text and text.isdigit() else 0
        return stats

    # Client Logs methods
    async def navigate_to_client_logs(self):
        """Navigate to client logs tab."""
        await self.click_tab("client_logs")

    async def filter_client_logs(
        self,
        modem_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ):
        """Apply filters to client logs."""
        if modem_id:
            await self.page.locator("#clientLogsModemFilter").fill(modem_id)
        if start_date:
            await self.page.locator("#clientLogsStartDate").fill(start_date)
        if end_date:
            await self.page.locator("#clientLogsEndDate").fill(end_date)

    # User Activity methods
    async def navigate_to_user_activity(self):
        """Navigate to user activity tab."""
        await self.click_tab("user_activity")

    # Toast/notification methods
    async def get_toast_message(self) -> str:
        """Get the current toast notification message."""
        toast = self.page.locator(".toast, .notification, .alert")
        if await toast.is_visible():
            return await toast.text_content()
        return ""

    async def wait_for_toast(self, timeout: int = 5000):
        """Wait for a toast notification to appear."""
        toast = self.page.locator(".toast, .notification, .alert")
        await toast.wait_for(timeout=timeout)
