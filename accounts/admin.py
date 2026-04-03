from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'user_type', 'teacher_title', 'student_number', 'department')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'student_number')
    list_filter = ('user_type', 'teacher_title', 'department')


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    extra = 0


class UserAdmin(BaseUserAdmin):
    inlines = (ProfileInline,)
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_active', 'get_user_type')
    list_filter = ('is_active', 'profile__user_type')
    list_editable = ('is_active',)
    
    def get_user_type(self, obj):
        if hasattr(obj, 'profile'):
            return obj.profile.get_user_type_display()
        return '-'
    get_user_type.short_description = 'User Type'


admin.site.unregister(User)
admin.site.register(User, UserAdmin)
