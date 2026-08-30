"""Security helpers for user-supplied profile images."""

import warnings
from io import BytesIO
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps


MAX_PROFILE_IMAGE_SIZE = 5 * 1024 * 1024
MAX_PROFILE_IMAGE_PIXELS = 25_000_000
ALLOWED_PROFILE_IMAGE_FORMATS = {'JPEG', 'PNG', 'GIF'}


def sanitize_profile_image(uploaded_file):
    """Decode and re-encode an image so uploaded bytes can never be served as HTML."""

    if uploaded_file.size > MAX_PROFILE_IMAGE_SIZE:
        raise ValidationError('Profil fotoğrafı en fazla 5 MB olabilir.')

    try:
        uploaded_file.seek(0)
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(uploaded_file) as probe:
                if probe.format not in ALLOWED_PROFILE_IMAGE_FORMATS:
                    raise ValidationError('Yalnızca JPEG, PNG veya GIF görselleri yüklenebilir.')
                if probe.width * probe.height > MAX_PROFILE_IMAGE_PIXELS:
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
    has_alpha = image.mode in {'RGBA', 'LA'} or (image.mode == 'P' and 'transparency' in image.info)
    if has_alpha:
        image = image.convert('RGBA')
        output_format, extension = 'PNG', 'png'
        image.save(output, format=output_format, optimize=True)
    else:
        image = image.convert('RGB')
        output_format, extension = 'JPEG', 'jpg'
        image.save(output, format=output_format, quality=90, optimize=True)

    return ContentFile(output.getvalue(), name=f'profile_{uuid4().hex}.{extension}')
