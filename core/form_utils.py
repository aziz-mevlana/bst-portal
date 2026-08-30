"""Shared, server-backed form UX helpers."""

from django import forms


def configure_required_choice(field, prompt='Seçiniz'):
    """Add an empty prompt and require a real selection on client and server."""

    field.required = True
    field.widget.attrs.update({
        'required': True,
        'aria-required': 'true',
        'data-required-choice': 'true',
    })
    if isinstance(field, forms.ModelChoiceField):
        field.empty_label = prompt
        return field

    choices = [(value, label) for value, label in field.choices if str(value) != '']
    field.choices = [('', prompt), *choices]
    return field


def configure_optional_choice(field, prompt='Seçiniz (isteğe bağlı)'):
    """Make it explicit that an empty choice is allowed."""

    field.required = False
    if isinstance(field, forms.ModelChoiceField):
        field.empty_label = prompt
        return field

    choices = [(value, label) for value, label in field.choices if str(value) != '']
    field.choices = [('', prompt), *choices]
    return field
