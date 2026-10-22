from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Notification


@login_required
def notification_list(request):
    notifications = Notification.objects.filter(recipient=request.user)
    return render(request, 'notifications/list.html', {'notifications': notifications})


@login_required
@require_POST
def mark_read(request, pk):
    notification = get_object_or_404(Notification, pk=pk, recipient=request.user)
    notification.is_read = True
    notification.save(update_fields=['is_read'])
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True})
    return redirect('notifications:list')


@login_required
@require_POST
def mark_all_read(request):
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    return redirect('notifications:list')


def _is_ajax(request):
    return request.headers.get('x-requested-with') == 'XMLHttpRequest'


@login_required
@require_POST
def delete_notification(request, pk):
    deleted, _ = Notification.objects.filter(pk=pk, recipient=request.user).delete()
    if _is_ajax(request):
        return JsonResponse({'ok': bool(deleted)}, status=200 if deleted else 404)
    return redirect('notifications:list')


@login_required
@require_POST
def clear_all(request):
    deleted, _ = Notification.objects.filter(recipient=request.user).delete()
    if _is_ajax(request):
        return JsonResponse({'ok': True, 'deleted': deleted})
    return redirect('notifications:list')


@login_required
def unread_feed(request):
    """Small JSON feed the navbar polls to pop toast notifications for new items."""
    notifications = Notification.objects.filter(recipient=request.user, is_read=False).order_by('-created_at')[:5]
    data = [{'id': n.id, 'message': n.message, 'category': n.category} for n in notifications]
    return JsonResponse({'count': len(data), 'notifications': data})
