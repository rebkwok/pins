from django.db.models import Q

# Hidden users for superusers to view the admin as a role (one per group, see
# dashboard/view_as.py), which aren't real people
VIEW_AS_USERNAME_PREFIX = "view-as-"


def is_view_as_user(user):
    return user.get_username().startswith(VIEW_AS_USERNAME_PREFIX)


def real_users_q():
    """A Q for users who aren't the view-as preview users"""
    return ~Q(username__startswith=VIEW_AS_USERNAME_PREFIX)
