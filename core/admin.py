from django.contrib import admin
from .models import Participant, Event, EventAttendance, MessageTemplate, MessageLog, Match

@admin.register(Participant)
class ParticipantAdmin(admin.ModelAdmin):
    list_display = ('first_name', 'last_name', 'role', 'level', 'is_active')
    list_filter = ('role', 'level', 'is_active')
    search_fields = ('first_name', 'last_name', 'phone_number')

@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ('date', 'time', 'location')
    list_filter = ('date',)

@admin.register(EventAttendance)
class EventAttendanceAdmin(admin.ModelAdmin):
    list_display = ('participant', 'event', 'status', 'role_for_event', 'timestamp')
    list_filter = ('status', 'event')
    search_fields = ('participant__first_name', 'participant__last_name', 'event__date')

@admin.register(MessageTemplate)
class MessageTemplateAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name', 'body')

@admin.register(MessageLog)
class MessageLogAdmin(admin.ModelAdmin):
    list_display = ('event', 'template', 'status', 'timestamp')
    list_filter = ('status', 'event')
    search_fields = ('rendered_text', 'error_message')

@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ('event', 'leader', 'follower', 'is_rotation')
    list_filter = ('event', 'is_rotation')
