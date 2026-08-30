from django import forms

from .models import Article


MAX_IMAGE_SIZE = 5 * 1024 * 1024


class ArticleForm(forms.ModelForm):
    class Meta:
        model = Article
        fields = [
            'title', 'summary', 'content', 'source', 'source_url', 'image', 'image_url',
            'article_type', 'article_category', 'category', 'is_homepage', 'is_featured',
        ]
        labels = {
            'title': 'Başlık', 'summary': 'Kısa özet', 'content': 'İçerik',
            'source': 'Kaynak adı', 'source_url': 'Harici kaynak bağlantısı',
            'image': 'Haber görseli', 'image_url': 'Harici görsel bağlantısı',
            'article_type': 'Haber türü', 'article_category': 'Haber kategorisi',
            'category': 'Genel kategori', 'is_homepage': 'Ana sayfada göster',
            'is_featured': 'Öne çıkan haber',
        }

    def clean_image(self):
        image = self.cleaned_data.get('image')
        if not image:
            return image
        if image.size > MAX_IMAGE_SIZE:
            raise forms.ValidationError('Görsel en fazla 5 MB olabilir.')
        content_type = getattr(image, 'content_type', '')
        if content_type and not content_type.startswith('image/'):
            raise forms.ValidationError('Yalnızca görsel dosyası yükleyebilirsiniz.')
        return image
