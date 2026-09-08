"""Security helpers for user-supplied profile images."""

from core.image_uploads import sanitize_image_upload


MAX_PROFILE_IMAGE_SIZE = 15 * 1024 * 1024
MAX_PROFILE_IMAGE_PIXELS = 25_000_000
ALLOWED_PROFILE_IMAGE_FORMATS = {'JPEG', 'PNG', 'GIF', 'WEBP'}


def sanitize_profile_image(uploaded_file):
    """Decode and re-encode an image so uploaded bytes can never be served as HTML."""
    return sanitize_image_upload(
        uploaded_file,
        filename_prefix='profile',
        max_size=MAX_PROFILE_IMAGE_SIZE,
        max_pixels=MAX_PROFILE_IMAGE_PIXELS,
        allowed_formats=ALLOWED_PROFILE_IMAGE_FORMATS,
    )
