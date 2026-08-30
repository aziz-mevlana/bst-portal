from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from accounts.policies import is_admin
from core.audit import record_audit_event
from core.forms import FooterLinkFormSet
from core.models import FooterLink


@login_required
@require_http_methods(['GET', 'POST'])
def footer_settings(request):
    if not is_admin(request.user):
        raise PermissionDenied
    formset = FooterLinkFormSet(
        request.POST if request.method == 'POST' else None,
        queryset=FooterLink.objects.all(), prefix='links',
    )
    if request.method == 'POST' and formset.is_valid():
        with transaction.atomic():
            formset.save()
            record_audit_event(actor=request.user, action='site.footer_updated', request=request)
        messages.success(request, 'Footer bağlantıları güncellendi.')
        return redirect('dashboard:footer_settings')
    return render(request, 'dashboard/footer_settings.html', {'formset': formset})
