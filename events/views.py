from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Event
from django.http import JsonResponse
from django.template.loader import render_to_string

PAGE_SIZE = 12

def _user_can_manage_event(user, event=None):
    if not user.is_authenticated:
        return False
    profile = getattr(user, 'profile', None)
    user_type = getattr(profile, 'user_type', None)
    if user_type in ('staff_student', 'teacher'):
        return True
    if event and event.created_by_id == user.id:
        return True
    return False

def event_list(request):
    show_create_card = request.user.is_authenticated and hasattr(request.user, 'profile') and request.user.profile.user_type in ('staff_student', 'teacher')
    page_size = PAGE_SIZE - 1 if show_create_card else PAGE_SIZE
    events = Event.objects.filter(is_active=True)[:page_size]
    total_count = Event.objects.filter(is_active=True).count()
    has_more = total_count > page_size
    return render(request, 'events/event_list.html', {
        'events': events,
        'has_more': has_more,
        'next_offset': page_size,
        'total_count': total_count
    })

def event_load_more(request):
    offset = int(request.GET.get('offset', 0))
    limit = PAGE_SIZE
    
    events = Event.objects.filter(is_active=True)[offset:offset + limit]
    total_count = Event.objects.filter(is_active=True).count()
    has_more = offset + limit < total_count
    
    html = render_to_string('events/partials/event_item.html', {'events': events})
    
    return JsonResponse({
        'items': html,
        'has_more': has_more,
        'next_offset': offset + limit
    })

def event_detail(request, event_id):
    try:
        event = Event.objects.get(id=event_id, is_active=True)
        return render(request, 'events/event_detail.html', {'event': event})
    except Event.DoesNotExist:
        messages.error(request, 'Etkinlik bulunamadı.')
        return redirect('events:event_list')

@login_required
def create_event(request):
    if request.user.profile.user_type != 'staff_student' and request.user.profile.user_type != 'teacher':
        return redirect('events:event_list')
    
    if request.method == 'POST':
        title = request.POST.get('title')
        description = request.POST.get('description')
        event_type = request.POST.get('event_type')
        location = request.POST.get('location')
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        image = request.FILES.get('image')
        event = Event.objects.create(
            title=title,
            description=description,
            event_type=event_type,
            location=location,
            start_date=start_date,
            end_date=end_date,
            image=image,
            created_by=request.user
        )
        messages.success(request, 'Etkinlik başarıyla oluşturuldu.')
        return redirect('events:event_detail', event_id=event.id)
    return render(request, 'events/create_event.html', {
        'submit_label': 'Oluştur',
        'page_title': 'Yeni Etkinlik Oluştur',
        'page_description': 'Yetkili kullanıcılar etkinlikleri buradan ekleyebilir.'
    })

@login_required
def edit_event(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    if not _user_can_manage_event(request.user, event):
        messages.error(request, 'Bu etkinliği düzenleme yetkiniz yok.')
        return redirect('events:event_detail', event_id=event.id)

    if request.method == 'POST':
        event.title = request.POST.get('title')
        event.description = request.POST.get('description')
        event.event_type = request.POST.get('event_type')
        event.location = request.POST.get('location')
        event.start_date = request.POST.get('start_date')
        event.end_date = request.POST.get('end_date')
        image = request.FILES.get('image')
        if image:
            event.image = image
        event.save()
        messages.success(request, 'Etkinlik başarıyla güncellendi.')
        return redirect('events:event_detail', event_id=event.id)

    return render(request, 'events/create_event.html', {
        'event_obj': event,
        'submit_label': 'Güncelle',
        'page_title': 'Etkinliği Düzenle',
        'page_description': 'Etkinlik bilgilerini güncelleyin ve kaydedin.'
    })

@login_required
def delete_event(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    if not _user_can_manage_event(request.user, event):
        messages.error(request, 'Bu etkinliği silme yetkiniz yok.')
        return redirect('events:event_detail', event_id=event.id)

    if request.method == 'POST':
        event.delete()
        messages.success(request, 'Etkinlik başarıyla silindi.')
        return redirect('events:event_list')

    return redirect('events:edit_event', event_id=event.id)
