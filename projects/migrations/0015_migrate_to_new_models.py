# Generated migration for data transfer

from django.db import migrations


def migrate_project_data(apps, schema_editor):
    """Migrate data from old models to new models"""
    
    # Get models
    OldRequest = apps.get_model('projects', 'Request')
    OldRespons = apps.get_model('projects', 'Respons')
    OldResponsUpdate = apps.get_model('projects', 'ResponsUpdate')
    OldComment = apps.get_model('projects', 'Comment')
    
    ProjectRequest = apps.get_model('projects', 'ProjectRequest')
    Project = apps.get_model('projects', 'Project')
    ProjectUpdate = apps.get_model('projects', 'ProjectUpdate')
    ProjectComment = apps.get_model('projects', 'ProjectComment')
    
    ProjectCategory = apps.get_model('projects', 'ProjectCategory')
    Technology = apps.get_model('projects', 'Technology')
    User = apps.get_model('auth', 'User')
    
    # Migrate Request to ProjectRequest
    for old_request in OldRequest.objects.all():
        new_request = ProjectRequest.objects.create(
            title=old_request.title,
            course=old_request.course,
            duration=old_request.duration,
            team_size=old_request.team_size,
            teacher=old_request.teacher,
            created_at=old_request.created_at,
            updated_at=old_request.updated_at
        )
    
    # Migrate Respons to Project
    for old_project in OldRespons.objects.all():
        # Find corresponding new request
        old_request = old_project.request
        new_request = ProjectRequest.objects.filter(
            title=old_request.title,
            teacher=old_request.teacher,
            created_at=old_request.created_at
        ).first()
        
        if new_request:
            new_project = Project.objects.create(
                project_request=new_request,
                title=old_project.title,
                advisor=old_project.advisor,
                description=old_project.description,
                project_link=old_project.project_link,
                created_by=old_project.created_by,
                created_at=old_project.created_at,
                updated_at=old_project.updated_at,
                status=old_project.status
            )
            
            # Migrate many-to-many relationships
            new_project.team.set(old_project.team.all())
            new_project.categories.set(old_project.categories.all())
            new_project.technologies.set(old_project.technologies.all())
            
            # Migrate related updates
            for old_update in old_project.updates.all():
                new_update = ProjectUpdate.objects.create(
                    project=new_project,
                    title=old_update.title,
                    note=old_update.note,
                    created_by=old_update.created_by,
                    created_at=old_update.updated_at
                )
            
            # Migrate related comments
            for old_comment in old_project.comments.all():
                new_comment = ProjectComment.objects.create(
                    project=new_project,
                    author=old_comment.author,
                    content=old_comment.content,
                    created_at=old_comment.created_at
                )


def reverse_migrate_project_data(apps, schema_editor):
    """Reverse migration - not implemented for safety"""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0014_alter_projectcategory_options_and_more'),
    ]

    operations = [
        migrations.RunPython(migrate_project_data, reverse_migrate_project_data),
    ]