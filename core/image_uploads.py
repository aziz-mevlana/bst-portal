"""Shared validation and safe re-encoding for user-supplied images."""

import warnings
from io import BytesIO
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps


DEFAULT_MAX_IMAGE_SIZE = 15 * 1024 * 1024
DEFAULT_MAX_IMAGE_PIXELS = 25_000_000
DEFAULT_ALLOWED_IMAGE_FORMATS = frozenset({'JPEG', 'PNG', 'WEBP'})


def sanitize_image_upload(
    uploaded_file,
    *,
    filename_prefix='image',
    max_size=DEFAULT_MAX_IMAGE_SIZE,
    max_pixels=DEFAULT_MAX_IMAGE_PIXELS,
    allowed_formats=DEFAULT_ALLOWED_IMAGE_FORMATS,
):
    """Decode and re-encode an upload, returning inert JPEG or PNG bytes."""

    if not uploaded_file or uploaded_file.size <= 0:
        raise ValidationError('Boş bir görsel dosyası yüklenemez.')
    if uploaded_file.size > max_size:
        raise ValidationError(f'Görsel en fazla {max_size // (1024 * 1024)} MB olabilir.')

    allowed_formats = {str(item).upper() for item in allowed_formats}
    try:
        uploaded_file.seek(0)
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(uploaded_file) as probe:
                image_format = (probe.format or '').upper()
                if image_format not in allowed_formats:
                    raise ValidationError('Yalnızca JPG/JPEG, PNG veya WEBP görsel yükleyebilirsiniz.')
                if probe.width * probe.height > max_pixels:
                    raise ValidationError('Görsel çözünürlüğü güvenli sınırı aşıyor.')
                probe.verify()

        uploaded_file.seek(0)
        with Image.open(uploaded_file) as decoded:
            decoded.seek(0)
            image = ImageOps.exif_transpose(decoded).copy()
    except ValidationError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValidationError('Görsel çözünürlüğü güvenli sınırı aşıyor.') from exc
    except Exception as exc:
        raise ValidationError('Geçerli bir görsel dosyası yükleyin.') from exc
    finally:
        try:
            uploaded_file.seek(0)
        except (AttributeError, OSError):
            pass

    output = BytesIO()
    has_alpha = image.mode in {'RGBA', 'LA'} or (
        image.mode == 'P' and 'transparency' in image.info
    )
    if has_alpha:
        image.convert('RGBA').save(output, format='PNG', optimize=True)
        extension = 'png'
    else:
        image.convert('RGB').save(output, format='JPEG', quality=90, optimize=True)
        extension = 'jpg'

    return ContentFile(
        output.getvalue(),
        name=f'{filename_prefix}_{uuid4().hex}.{extension}',
    )
