from django.core.files.storage import FileSystemStorage, storages
import uuid


class ProjectMilestonePrivateStorage(FileSystemStorage):
    @property
    def base_url(self):
        return None

    def url(self, name):
        raise NotImplementedError('Milestone files require an authorized endpoint.')


def project_milestone_private_storage():
    return storages['project_milestone_private']


def milestone_file_path(instance, filename):
    return f'project-milestones/{uuid.uuid4().hex}'
