import json
import requests
from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.db.models import Count, Q
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import Event, Participant, EventAttendance, AttendanceStatus, Match, MessageTemplate, MessageLog, RecurringSchedule
from .tasks import scheduled_rsvp_announcement, scheduled_match_announcement

def rsvp_view(request, event_id):
    event = get_object_or_404(Event, id=event_id)
    is_expired = timezone.now() > event.rsvp_deadline if event.rsvp_deadline else False
    
    if request.method == 'POST':
        if is_expired:
            return render(request, 'core/rsvp.html', {'event': event, 'error': 'Le adesioni sono chiuse.', 'is_expired': True})
            
        phone = request.POST.get('phone')
        status = request.POST.get('status')
        role = request.POST.get('role')
        
        try:
            participant = Participant.objects.get(phone_number=phone)
            attendance, created = EventAttendance.objects.get_or_create(
                participant=participant,
                event=event,
                defaults={'status': status, 'role_for_event': role or participant.role}
            )
            if not created:
                attendance.status = status
                if role:
                    attendance.role_for_event = role
                attendance.save()
            return render(request, 'core/rsvp_success.html', {'event': event, 'participant': participant, 'status': status})
        except Participant.DoesNotExist:
            return render(request, 'core/rsvp.html', {'event': event, 'error': 'Numero non trovato.'})
            
    return render(request, 'core/rsvp.html', {'event': event, 'is_expired': is_expired})

@login_required(login_url='/admin/login/')
def wa_status(request):
    try:
        # Assumiamo che il wa-gateway sia in locale sulla porta 4002
        response = requests.get('http://127.0.0.1:4002/api/status', timeout=3)
        return JsonResponse(response.json())
    except Exception as e:
        return JsonResponse({'status': 'OFFLINE', 'error': str(e)})

@login_required(login_url='/admin/login/')
def wa_logout(request):
    if request.method == 'POST':
        try:
            response = requests.post('http://127.0.0.1:4002/api/logout', timeout=5)
            data = response.json()
            if data.get('success'):
                return JsonResponse({'success': True, 'message': 'Disconnesso. Verrai reindirizzato al login WhatsApp...'})
            else:
                return JsonResponse({'success': False, 'message': data.get('error', 'Errore sconosciuto.')})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=500)
    return JsonResponse({'success': False}, status=405)

@login_required(login_url='/admin/login/')
def onboarding(request):
    try:
        response = requests.get('http://127.0.0.1:4002/api/status', timeout=3)
        data = response.json()
        if data.get('status') == 'CONNECTED':
            return redirect('core:dashboard')
    except Exception:
        pass # Gateway offline
        
    return render(request, 'core/onboarding.html')

@login_required(login_url='/admin/login/')
def dashboard(request):
    try:
        response = requests.get('http://127.0.0.1:4002/api/status', timeout=2)
        data = response.json()
        if data.get('status') != 'CONNECTED':
            return redirect('core:onboarding')
    except Exception:
        # Se c'è errore, redirigiamo comunque all'onboarding per informare l'utente
        return redirect('core:onboarding')

    from .tasks import auto_generate_events
    auto_generate_events()
    
    now = timezone.now()
    next_week = now + timedelta(days=7)
    
    upcoming_event = Event.objects.filter(date__gte=now.date(), date__lte=next_week.date()).order_by('date', 'time').first()
    
    context = {
        'upcoming_event': upcoming_event,
    }
    
    if upcoming_event:
        attendances = EventAttendance.objects.filter(event=upcoming_event, status=AttendanceStatus.ATTENDING)
        leaders = sum(1 for a in attendances if (a.role_for_event or a.participant.role) == 'leader')
        followers = sum(1 for a in attendances if (a.role_for_event or a.participant.role) == 'follower')
        both = sum(1 for a in attendances if (a.role_for_event or a.participant.role) == 'both')
        
        context['stats'] = {
            'total': attendances.count(),
            'leaders': leaders,
            'followers': followers,
            'both': both,
        }
        
        context['matches'] = Match.objects.filter(event=upcoming_event, is_rotation=False)
        context['rotations'] = Match.objects.filter(event=upcoming_event, is_rotation=True)
        
    context['rsvp_template'] = MessageTemplate.objects.filter(name='RSVP').first()
    context['match_template'] = MessageTemplate.objects.filter(name='MATCH').first()
    context['recent_logs'] = MessageLog.objects.order_by('-timestamp')[:10]
    context['recurring'] = RecurringSchedule.objects.first()
        
    return render(request, 'core/dashboard.html', context)

@login_required
def update_group(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            event = Event.objects.get(id=data.get('event_id'))
            event.whatsapp_group_name = data.get('group_name')
            event.save()
            return JsonResponse({'success': True, 'message': 'Gruppo salvato!'})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=400)
    return JsonResponse({'success': False}, status=405)

@login_required
def trigger_rsvp(request):
    if request.method == 'POST':
        try:
            now = timezone.now()
            next_week = now + timedelta(days=7)
            upcoming_event = Event.objects.filter(date__gte=now.date(), date__lte=next_week.date()).order_by('date', 'time').first()
            if upcoming_event:
                scheduled_rsvp_announcement(force_event_id=upcoming_event.id)
            return JsonResponse({'success': True, 'message': 'Adesioni avviate!'})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=500)
    return JsonResponse({'success': False}, status=405)

@login_required
def trigger_match(request):
    if request.method == 'POST':
        try:
            now = timezone.now()
            next_week = now + timedelta(days=7)
            upcoming_event = Event.objects.filter(date__gte=now.date(), date__lte=next_week.date()).order_by('date', 'time').first()
            if upcoming_event:
                scheduled_match_announcement(force_event_id=upcoming_event.id)
            return JsonResponse({'success': True, 'message': 'Coppie generate e inviate!'})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=500)
    return JsonResponse({'success': False}, status=405)

@login_required
def update_templates(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            rsvp_text = data.get('rsvp_text')
            match_text = data.get('match_text')
            
            if rsvp_text is not None:
                MessageTemplate.objects.update_or_create(name='RSVP', defaults={'body': rsvp_text})
            if match_text is not None:
                MessageTemplate.objects.update_or_create(name='MATCH', defaults={'body': match_text})
                
            return JsonResponse({'success': True, 'message': 'Template salvati!'})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=500)
    return JsonResponse({'success': False}, status=405)

@login_required
def update_scheduling(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            event = Event.objects.get(id=data.get('event_id'))
            
            from django.utils.dateparse import parse_datetime
            if data.get('rsvp_date'):
                dt = parse_datetime(data.get('rsvp_date'))
                if timezone.is_naive(dt): dt = timezone.make_aware(dt)
                event.rsvp_send_at = dt
            else:
                event.rsvp_send_at = None
                
            if data.get('match_date'):
                dt = parse_datetime(data.get('match_date'))
                if timezone.is_naive(dt): dt = timezone.make_aware(dt)
                event.match_send_at = dt
            else:
                event.match_send_at = None
                
            event.save()
            return JsonResponse({'success': True, 'message': 'Schedulazione aggiornata!'})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=500)
    return JsonResponse({'success': False}, status=405)

@login_required
def update_recurring(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            from datetime import datetime, date
            
            # Recupera o crea la schedulazione
            recurring = RecurringSchedule.objects.first()
            if not recurring:
                recurring = RecurringSchedule()
                
            recurring.days_of_week = data.get('days_of_week', "0")
            recurring.time = datetime.strptime(data.get('time', '21:00'), '%H:%M').time()
            
            if data.get('start_date'):
                recurring.start_date = datetime.strptime(data.get('start_date'), '%Y-%m-%d').date()
            if data.get('end_date'):
                recurring.end_date = datetime.strptime(data.get('end_date'), '%Y-%m-%d').date()
                
            recurring.rsvp_days_before = int(data.get('rsvp_days', 0))
            recurring.rsvp_time = datetime.strptime(data.get('rsvp_time', '10:00'), '%H:%M').time()
            
            if data.get('match_time'):
                recurring.match_time = datetime.strptime(data.get('match_time', '19:00'), '%H:%M').time()
            if 'rsvp_mode' in data:
                recurring.rsvp_mode = data.get('rsvp_mode')
            if 'gemini_api_key' in data:
                recurring.gemini_api_key = data.get('gemini_api_key')
            if 'debug_mode' in data:
                recurring.debug_mode = data.get('debug_mode')
                
            recurring.save()
            
            # Applica le nuove tempistiche anche agli eventi futuri già creati
            now = timezone.now()
            future_events = Event.objects.filter(date__gte=now.date())
            for event in future_events:
                rsvp_dt = datetime.combine(event.date - timedelta(days=recurring.rsvp_days_before), recurring.rsvp_time)
                event.rsvp_send_at = timezone.make_aware(rsvp_dt)
                
                if recurring.match_time:
                    match_dt = datetime.combine(event.date, recurring.match_time)
                else:
                    match_dt = datetime.combine(event.date, recurring.time) - timedelta(hours=2)
                
                event.match_send_at = timezone.make_aware(match_dt)
                event.rsvp_deadline = event.match_send_at
                
                # Se l'utente sposta l'orario nel futuro, resettiamo i flag per permettere i test!
                if event.rsvp_send_at > now:
                    event.rsvp_sent = False
                if event.match_send_at > now:
                    event.match_sent = False
                    
                event.save()
            
            return JsonResponse({'success': True, 'message': 'Schedulazione Ricorrente Salvata!'})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=500)
    return JsonResponse({'success': False}, status=405)

@csrf_exempt
def poll_vote_webhook(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            print(f"WEBHOOK POLL RICEVUTO! Data: {data}")
            
            # Gestione Payload OpenWA vs Custom Locale
            voter_id = data.get('voter', '')
            selected_options = data.get('selectedOptions', [])
            
            if 'payload' in data:  # Formato OpenWA
                payload = data['payload']
                voter_id = payload.get('voter', payload.get('author', payload.get('from', '')))
                if isinstance(voter_id, dict):
                    voter_id = voter_id.get('_serialized', '') or voter_id.get('user', '')
                    
                selected_options = payload.get('selectedOptions', [])
                if not selected_options:
                    selected_options = [opt.get('name', '') for opt in payload.get('selectedOptions', []) if isinstance(opt, dict)]
            
            if not voter_id or selected_options is None:
                return JsonResponse({'success': True, 'message': 'Evento ignorato (non è un voto a un sondaggio o dati mancanti).'})
                
            phone_digits = ''.join(filter(str.isdigit, str(voter_id)))
            
            # Trova l'evento imminente
            now = timezone.now()
            next_week = now + timedelta(days=7)
            upcoming_event = Event.objects.filter(date__gte=now.date(), date__lte=next_week.date()).order_by('date', 'time').first()
            
            if not upcoming_event:
                return JsonResponse({'success': False, 'message': 'Nessun evento imminente trovato.'})
            
            # Cerca il partecipante usando le ultime 10 cifre del numero
            participant = None
            if len(phone_digits) >= 10:
                last_10 = phone_digits[-10:]
                for p in Participant.objects.all():
                    p_digits = ''.join(filter(str.isdigit, p.phone_number))
                    if p_digits.endswith(last_10):
                        participant = p
                        break
            
            if not participant:
                return JsonResponse({'success': False, 'message': 'Partecipante sconosciuto, voto ignorato.'})
            
            # Determina lo status
            is_attending = False
            for opt in selected_options:
                if 'Ci sono!' in opt:
                    is_attending = True
                    break
                    
            status = AttendanceStatus.ATTENDING if is_attending else AttendanceStatus.NOT_ATTENDING
            
            # Aggiorna la presenza
            EventAttendance.objects.update_or_create(
                event=upcoming_event,
                participant=participant,
                defaults={'status': status, 'role_for_event': participant.role}
            )
            
            return JsonResponse({'success': True, 'participant': str(participant), 'status': status})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=500)
    return JsonResponse({'success': False}, status=405)

@login_required
def list_participants(request):
    participants = Participant.objects.all().order_by('first_name', 'last_name')
    data = []
    for p in participants:
        data.append({
            'id': str(p.id),
            'first_name': p.first_name,
            'last_name': p.last_name,
            'phone_number': p.phone_number,
            'gender': p.gender,
            'role': p.role,
            'level': p.level,
            'is_active': p.is_active
        })
    return JsonResponse({'participants': data})

@login_required
def save_participant(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            p_id = data.get('id')
            
            defaults = {
                'first_name': data.get('first_name', ''),
                'last_name': data.get('last_name', ''),
                'phone_number': data.get('phone_number', ''),
                'gender': data.get('gender', 'M'),
                'role': data.get('role', 'leader'),
                'level': data.get('level', 'intermedio'),
                'is_active': data.get('is_active', True)
            }
            
            if p_id:
                participant, created = Participant.objects.update_or_create(id=p_id, defaults=defaults)
            else:
                participant = Participant.objects.create(**defaults)
                
            return JsonResponse({'success': True, 'message': 'Partecipante salvato con successo!'})
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=500)
    return JsonResponse({'success': False}, status=405)

@login_required
def delete_participant(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            p_id = data.get('id')
            if p_id:
                Participant.objects.filter(id=p_id).delete()
                return JsonResponse({'success': True, 'message': 'Partecipante eliminato!'})
            return JsonResponse({'success': False, 'message': 'ID mancante.'}, status=400)
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)}, status=500)
    return JsonResponse({'success': False}, status=405)
