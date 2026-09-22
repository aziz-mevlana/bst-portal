from django.core.files.storage import FileSystemStorage, storages


class PrivateFileSystemStorage(FileSystemStorage):
    """Local storage without a public URL surface."""

    @property
    def base_url(self):
        return None

    def url(self, name):
        raise NotImplementedError('Private CAPSTONE files require an authorized download endpoint.')


def capstone_private_storage():
    return storages['capstone_private']
