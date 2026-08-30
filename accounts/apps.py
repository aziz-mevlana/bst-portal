from django.apps import AppConfig
from django.db.models.signals import post_migrate


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'

    def ready(self):
        from .roles import bootstrap_bst_authority_group

        def bootstrap_roles(**kwargs):
            bootstrap_bst_authority_group()

        post_migrate.connect(bootstrap_roles, sender=self, dispatch_uid='accounts.bootstrap_bst_authority')
