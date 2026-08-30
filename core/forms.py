from django import forms
from django.forms import modelformset_factory

from .models import FooterLink


class FooterLinkForm(forms.ModelForm):
    class Meta:
        model = FooterLink
        fields = ['section', 'label', 'url', 'sort_order', 'is_active', 'open_new_tab']
        widgets = {
            'label': forms.TextInput(attrs={'placeholder': 'Örn. Katkıda bulunan kişi'}),
            'url': forms.TextInput(attrs={'placeholder': 'https://… veya /site-ici-adres/'}),
            'sort_order': forms.NumberInput(attrs={'min': 0}),
        }


FooterLinkFormSet = modelformset_factory(
    FooterLink, form=FooterLinkForm, extra=1, can_delete=True,
    max_num=100, validate_max=True, absolute_max=120,
)
