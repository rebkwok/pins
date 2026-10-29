from wagtail.admin.menu import MenuItem


class PermissionMenuItem(MenuItem):
    """An admin menu item only shown to users with the permission"""

    def __init__(self, *args, permission, **kwargs):
        super().__init__(*args, **kwargs)
        self.permission = permission

    def is_shown(self, request):
        return request.user.has_perm(self.permission)
