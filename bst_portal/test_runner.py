from django.db import connections
from django.test.runner import DiscoverRunner


class PortalTestRunner(DiscoverRunner):
    """Keep legacy CAPSTONE tests' empty-term starting state in test databases."""

    def setup_databases(self, **kwargs):
        old_config = super().setup_databases(**kwargs)
        from capstone.models import CapstoneTerm

        for alias in connections:
            connection = connections[alias]
            if connection.settings_dict.get('TEST', {}).get('MIRROR'):
                continue
            with connection.cursor() as cursor:
                if CapstoneTerm._meta.db_table not in connection.introspection.table_names(cursor):
                    continue
            # Migration 0009 seeds production. Existing tests create their own
            # 2026-2027 term, so remove only this fresh test-database seed.
            CapstoneTerm.objects.using(alias).filter(
                academic_year='2026-2027', semester='FALL',
                enrollments__isnull=True, capstone_projects__isnull=True,
            ).delete()
        return old_config
