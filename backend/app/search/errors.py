from app.core.exceptions import AppError


class ProfileIncompleteError(AppError):
    status = 409
    code = "profile-incomplete"
    title = "Set up your profile to see your feed"
