from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('rsvp/<str:event_id>/', views.rsvp_view, name='rsvp'),
    path('api/update-group/', views.update_group, name='update_group'),
    path('api/update-templates/', views.update_templates, name='update_templates'),
    path('api/update-scheduling/', views.update_scheduling, name='update_scheduling'),
    path('api/update-recurring/', views.update_recurring, name='update_recurring'),
    path('api/trigger-rsvp/', views.trigger_rsvp, name='trigger_rsvp'),
    path('api/trigger-match/', views.trigger_match, name='trigger_match'),
    path('api/webhook/poll-vote/', views.poll_vote_webhook, name='poll_vote_webhook'),
    path('onboarding/', views.onboarding, name='onboarding'),
    path('api/wa-status/', views.wa_status, name='wa_status'),
    path('api/wa-logout/', views.wa_logout, name='wa_logout'),
    path('api/participants/', views.list_participants, name='list_participants'),
    path('api/participants/save/', views.save_participant, name='save_participant'),
    path('api/participants/delete/', views.delete_participant, name='delete_participant'),
]
