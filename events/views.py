from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Event

def event_list(request):
    events = Event.objects.filter(is_active=True)
    return render(request, 'events/event_list.html', {'events': events})

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
    return render(request, 'events/create_event.html')