from django import forms
from core.image_uploads import sanitize_image_upload
from .models import Event


MAX_IMAGE_SIZE = 5 * 1024 * 1024


class EventForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = [
            'title', 'description', 'event_type', 'location', 'start_date', 'end_date', 'image',
            'allow_registration', 'capacity', 'registration_deadline', 'waitlist_enabled',
            'certificate_enabled',
        ]
        widgets = {
            'image': forms.ClearableFileInput(attrs={'accept': '.jpg,.jpeg,.png,.webp'}),
        }

    def clean(self):
        cleaned = super().clean()
        start_date = cleaned.get('start_date')
        end_date = cleaned.get('end_date')
        if start_date and end_date and end_date <= start_date:
            self.add_error('end_date', 'Bitiş tarihi başlangıç tarihinden sonra olmalıdır.')
        registration_deadline = cleaned.get('registration_deadline')
        if registration_deadline and start_date and registration_deadline > start_date:
            self.add_error('registration_deadline', 'Kayıt son tarihi etkinlik başlangıcından sonra olamaz.')
        return cleaned

    def clean_image(self):
        image = self.cleaned_data.get('image')
        if not image:
            return image
        return sanitize_image_upload(
            image,
            filename_prefix='event',
            max_size=MAX_IMAGE_SIZE,
        )


class EventFeedbackForm(forms.Form):
    rating = forms.IntegerField(min_value=1, max_value=5)
    comment = forms.CharField(required=False, max_length=2000, widget=forms.Textarea(attrs={'rows': 4}))
