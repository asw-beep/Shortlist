from app.core.exceptions import AppError, NotFoundError


class ProfileMissingError(NotFoundError):
    code = "profile-missing"
    title = "Create your profile first"


class UnknownLocationError(AppError):
    status = 422
    code = "unknown-location"
    title = "Location not recognised; use an Indian city name"


class LlmUnavailableError(AppError):
    status = 503
    code = "llm-unavailable"
    title = "Résumé reading is unavailable right now; fill the profile in by hand"


class ResumeTooLargeError(AppError):
    status = 413
    code = "resume-too-large"
    title = "Résumé PDFs can be at most 2 MB"


class UnreadableResumeError(AppError):
    status = 422
    code = "unreadable-resume"
    title = "Could not read text from this file; paste the text instead"


class ResumeMissingError(AppError):
    status = 422
    code = "resume-missing"
    title = "Upload a PDF or paste the text"
