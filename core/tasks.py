from datetime import timedelta
from django.utils import timezone
from django.template import Template, Context
from .models import Event, MessageTemplate, MessageLog
from .wa_client import send_whatsapp_message
from .services import generate_matches

def scheduled_rsvp_announcement(force_event_id=None):
    """
    Task programmato (da eseguire ogni minuto) per controllare gli eventi
    che devono inviare l'apertura adesioni.
    """
    now = timezone.now()
    
    if force_event_id:
        events = Event.objects.filter(id=force_event_id)
    else:
        # Prendi gli eventi in cui l'ora X è passata, ma il messaggio non è ancora stato inviato
        events = Event.objects.filter(rsvp_send_at__lte=now, rsvp_sent=False)
    
    from .models import RecurringSchedule
    schedule = RecurringSchedule.objects.first()
    rsvp_mode = schedule.rsvp_mode if schedule else 'POLL'
    
    for event in events:
        # Prendi il template di base
        template = MessageTemplate.objects.filter(name='RSVP').first()
        if not template:
            print("ERRORE: Nessun MessageTemplate trovato per RSVP.")
            continue
            
        # Renderizza il testo
        t = Template(template.body)
        c = Context({
            'event_date': event.date.strftime('%d/%m/%Y'),
            'deadline_time': event.match_send_at.strftime('%H:%M') if event.match_send_at else '',
            'rsvp_link': 'Rispondete al sondaggio!' if rsvp_mode == 'POLL' else 'Rispondete liberamente a questo messaggio!'
        })
        message = t.render(c)
        
        # Inizializza Log
        log = MessageLog(
            event=event,
            template=template,
            rendered_text=message,
            status='Inviato'
        )
        
        try:
            print(f"Inviando annuncio WhatsApp per evento {event.id} in modalità {rsvp_mode}...")
            
            if rsvp_mode == 'POLL':
                response = send_whatsapp_message(
                    event.whatsapp_group_name, 
                    message, 
                    is_group=True,
                    is_poll=True,
                    poll_options=["Ci sono! 🕺💃", "Non ci sono 🚫"]
                )
            else:
                response = send_whatsapp_message(
                    event.whatsapp_group_name, 
                    message, 
                    is_group=True
                )
            
            if response.get('success'):
                print("Messaggio adesioni inviato con successo.")
                event.rsvp_sent = True
                event.save()
            else:
                log.status = 'Errore'
                log.error_message = response.get('error', 'Unknown Error')
                
            log.save()
        except Exception as e:
            log.status = 'Errore'
            log.error_message = str(e)
            log.save()
            print(f"Errore durante l'invio: {e}")

def scheduled_match_announcement(force_event_id=None):
    """
    Task programmato (da eseguire ogni minuto) per generare le coppie
    e inviarle quando l'ora X scatta.
    """
    now = timezone.now()
    
    if force_event_id:
        events = Event.objects.filter(id=force_event_id)
    else:
        events = Event.objects.filter(match_send_at__lte=now, match_sent=False)
    
    for event in events:
        from .models import Match, RecurringSchedule, Participant, EventAttendance, AttendanceStatus
        import requests
        import json
        
        schedule = RecurringSchedule.objects.first()
        rsvp_mode = schedule.rsvp_mode if schedule else 'POLL'
        
        if schedule and schedule.gemini_api_key and rsvp_mode == 'LLM':
            print("Modalità LLM attiva: Analizzo le adesioni usando Gemini AI...")
            try:
                import google.generativeai as genai
                # 1. Recupera la chat
                since = int(event.rsvp_send_at.timestamp()) if event.rsvp_send_at else 0
                url = f"http://127.0.0.1:4002/api/chat-history?chatId={event.whatsapp_group_name}&sinceTs={since}"
                res = requests.get(url)
                if res.status_code == 200 and res.json().get('success'):
                    messages = res.json().get('messages', [])
                    transcript = ""
                    for m in messages:
                        transcript += f"[{m['sender']}]: {m['body']}\n"
                        
                    if transcript.strip():
                        # 2. Chiama Gemini
                        genai.configure(api_key=schedule.gemini_api_key)
                        model = genai.GenerativeModel('gemini-1.5-flash', generation_config={"response_mime_type": "application/json"})
                        prompt = f"""
Sei un assistente che estrae conferme di partecipazione da una chat di gruppo WhatsApp.
Devi restituire SOLO ED ESCLUSIVAMENTE un array JSON contenente l'ID del mittente (la stringa tra le parentesi quadre) di chi ha CONFERMATO la presenza per l'evento di oggi.
Chi dice di non esserci o fa chiacchiere inutili non deve essere incluso. Se una persona conferma e poi disdice, NON includerlo.
Formato di output richiesto: ["393331234567@c.us", "393450000000@c.us"]
Trascrizione Chat:
{transcript}
                        """
                        response = model.generate_content(prompt)
                        try:
                            confirmed_senders = json.loads(response.text)
                            print(f"Gemini ha trovato i seguenti confermati: {confirmed_senders}")
                            
                            # 3. Aggiorna il database
                            # Mettiamo prima tutti a NOT_ATTENDING per resettare le adesioni
                            EventAttendance.objects.filter(event=event).update(status=AttendanceStatus.NOT_ATTENDING)
                            
                            # Aggiungiamo alla lista dei confermati
                            confirmed_list = []
                            for sender in confirmed_senders:
                                phone_digits = ''.join(filter(str.isdigit, sender))
                                if len(phone_digits) >= 10:
                                    last_10 = phone_digits[-10:]
                                    found = False
                                    for p in Participant.objects.all():
                                        p_digits = ''.join(filter(str.isdigit, p.phone_number))
                                        if p_digits.endswith(last_10):
                                            EventAttendance.objects.update_or_create(
                                                event=event,
                                                participant=p,
                                                defaults={'status': AttendanceStatus.ATTENDING, 'role_for_event': p.role}
                                            )
                                            confirmed_list.append(f"{p.first_name} {p.last_name}")
                                            found = True
                                            break
                                    if not found:
                                        # Inseriamo il numero di telefono se non è in rubrica
                                        clean_number = "+" + phone_digits if phone_digits else sender
                                        confirmed_list.append(clean_number)
                                        
                        except json.JSONDecodeError:
                            print(f"Errore parsing JSON da Gemini: {response.text}")
                    else:
                        print("Nessun messaggio trovato nella finestra di tempo.")
                        confirmed_list = []
            except Exception as e:
                print(f"Errore durante integrazione Gemini: {e}")
                confirmed_list = []
                
        # Prima di creare il messaggio finale, generiamo le coppie
        from .services import generate_matches
        match_stats = generate_matches(event.id)
        
        # Recupera le coppie appena generate
        matches = Match.objects.filter(event=event, is_rotation=False)
        rotations = Match.objects.filter(event=event, is_rotation=True)
        
        # Costruisci il messaggio formattato
        msg = f"✅ *COPPIE GENERATE - {event.date.strftime('%d/%m')}*\n\n"
        
        if matches.exists():
            for i, m in enumerate(matches, 1):
                msg += f"{i}. 🕺 {m.leader.first_name if m.leader else '???'} - 💃 {m.follower.first_name if m.follower else '???'}\n"
        else:
            msg += "Nessuna coppia formata al momento.\n"
            
        if rotations.exists():
            msg += "\n🔄 *In Rotazione:*\n"
            for r in rotations:
                p = r.leader or r.follower
                msg += f"- {p.first_name} {p.last_name}\n"
                
        # Inizializza Log
        template, _ = MessageTemplate.objects.get_or_create(name="MATCH", defaults={'body': 'Elenco partecipanti'})
        log = MessageLog(
            event=event,
            template=template,
            rendered_text=msg,
            status='Inviato'
        )
        
        try:
            response = send_whatsapp_message(to=event.whatsapp_group_name, message=msg, is_group=True)
            if response.get('success'):
                event.match_sent = True
                event.save()
                log.status = 'Inviato'
            else:
                log.status = 'Errore'
                log.error_message = response.get('error', 'Unknown Error')
            log.save()
        except Exception as e:
            log.status = 'Errore'
            log.error_message = str(e)
            log.save()

def auto_generate_events():
    """
    Controlla la RecurringSchedule e, se il prossimo evento non esiste, lo crea.
    """
    from .models import RecurringSchedule, Event
    import datetime
    from django.utils import timezone
    
    schedule = RecurringSchedule.objects.first()
    if not schedule:
        return
        
    now = timezone.now()
    today = now.date()
    
    # Calcola le date dei prossimi eventi in base ai giorni desiderati
    # I giorni sono stringhe separate da virgole (es "0,2")
    if not schedule.days_of_week:
        return
        
    days = [int(x.strip()) for x in schedule.days_of_week.split(',') if x.strip().isdigit()]
    if not days:
        return
        
    for target_day in days:
        days_ahead = target_day - today.weekday()
        if days_ahead < 0: # Already passed this week, check next week
            days_ahead += 7
            
        next_event_date = today + datetime.timedelta(days=days_ahead)
        
        # Ignora eventi fuori dal range start_date e end_date
        if schedule.start_date and next_event_date < schedule.start_date:
            continue
        if schedule.end_date and next_event_date > schedule.end_date:
            continue
            
        # Controlla se l'evento esiste già per questa data
        existing_event = Event.objects.filter(date=next_event_date).first()
        
        if not existing_event:
            # Crea l'evento!
            
            # Calcola le date di rsvp e match basate sulla schedule
            rsvp_dt = datetime.datetime.combine(next_event_date - datetime.timedelta(days=schedule.rsvp_days_before), schedule.rsvp_time)
            rsvp_dt = timezone.make_aware(rsvp_dt)
            
            # Il match lo impostiamo usando match_time dalla schedule
            if hasattr(schedule, 'match_time') and schedule.match_time:
                match_dt = datetime.datetime.combine(next_event_date, schedule.match_time)
            else:
                match_dt = datetime.datetime.combine(next_event_date, schedule.time) - datetime.timedelta(hours=2)
            match_dt = timezone.make_aware(match_dt)
            
            # Recupera il gruppo dall'ultimo evento per comodità
            last_event = Event.objects.order_by('-date').first()
            group_name = last_event.whatsapp_group_name if last_event else ""
            
            new_event = Event.objects.create(
                date=next_event_date,
                time=schedule.time,
                location="Sede Tango Manager",
                whatsapp_group_name=group_name,
                rsvp_send_at=rsvp_dt,
                match_send_at=match_dt,
                rsvp_deadline=match_dt  # Usa match_dt come scadenza RSVP
            )
            print(f"Creato automaticamente un nuovo evento per il {next_event_date}!")
        else:
            print(f"Evento per il {next_event_date} esiste già.")
