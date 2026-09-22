from django.shortcuts import render


def bad_request(request, exception):
    return render(request, 'errors/400.html', status=400)


def permission_denied(request, exception):
    return render(request, 'errors/403.html', status=403)


def page_not_found(request, exception):
    return render(request, 'errors/404.html', {
        'meta_title': '404 | BST Portal',
        'meta_description': 'Aradığınız sayfa BST Portal üzerinde bulunamadı.',
        'meta_robots': 'noindex,nofollow',
    }, status=404)


def server_error(request):
    return render(request, 'errors/500.html', status=500)
