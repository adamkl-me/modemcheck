"""Page Object Model for ModemCheck Cloud UI tests."""
from .login_page import LoginPage
from .admin_page import AdminPage
from .viewer_page import ViewerPage

__all__ = ["LoginPage", "AdminPage", "ViewerPage"]
