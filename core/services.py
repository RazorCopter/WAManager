import random
from collections import defaultdict
from django.db.models import Q
from .models import Event, EventAttendance, Match, Role, AttendanceStatus

def generate_matches(event_id):
    """
    Algoritmo di abbinamento coppie per un dato evento.
    - Risolve i ruoli "BOTH" per equilibrare i numeri.
    - Genera coppie evitando abbinamenti già avvenuti negli ultimi 3 eventi.
    - Gestisce la disparità assegnando il flag "is_rotation=True" a chi resta spaiato.
    """
    event = Event.objects.get(id=event_id)
    
    # 1. Pulisci match pregressi per questo evento in caso di ricalcolo
    Match.objects.filter(event=event).delete()
    
    attendances = EventAttendance.objects.filter(event=event, status=AttendanceStatus.ATTENDING)
    
    leaders = []
    followers = []
    both = []
    
    # Estrai i ruoli
    for att in attendances:
        r = att.role_for_event if att.role_for_event else att.participant.role
        if r == Role.LEADER:
            leaders.append(att.participant)
        elif r == Role.FOLLOWER:
            followers.append(att.participant)
        else:
            both.append(att.participant)
            
    # 2. Assegna chi fa "BOTH" al ruolo più carente
    random.shuffle(both)
    for p in both:
        if len(leaders) <= len(followers):
            leaders.append(p)
        else:
            followers.append(p)
            
    # 3. Costruisci lo storico per evitare ripetizioni
    # Recupera gli ultimi 3 eventi precedenti a questo
    recent_events = Event.objects.filter(date__lt=event.date).order_by('-date')[:3]
    recent_matches = Match.objects.filter(event__in=recent_events, is_rotation=False)
    
    history = defaultdict(set)
    for m in recent_matches:
        if m.leader and m.follower:
            history[m.leader.id].add(m.follower.id)
            history[m.follower.id].add(m.leader.id)
            
    # 4. Abbinamento Greedy (con vincolo di Sesso Uomo/Donna)
    random.shuffle(leaders)
    random.shuffle(followers)
    
    unmatched_leaders = leaders.copy()
    unmatched_followers = followers.copy()
    
    pairs = []
    
    # Cerchiamo coppie che NON hanno ballato insieme di recente E sono di sesso opposto
    for l in list(unmatched_leaders):
        possible_followers = [f for f in unmatched_followers if f.id not in history[l.id] and f.gender != l.gender]
        
        # Fallback: Se non c'è nessuno con cui non ha ballato di recente, 
        # accontentiamoci di una persona di sesso opposto anche se hanno già ballato
        if not possible_followers:
            possible_followers = [f for f in unmatched_followers if f.gender != l.gender]
            
        if possible_followers:
            # Prendi il primo possibile (sono già stati mischiati)
            f = possible_followers[0]
            pairs.append((l, f))
            unmatched_leaders.remove(l)
            unmatched_followers.remove(f)
            
    # Se restano persone, ma non ci sono più accoppiamenti di sesso opposto, 
    # andranno in rotazione. Non accoppiamo forzatamente persone dello stesso sesso 
    # dato che il requisito è "le coppie sono sempre Uomo Donna".
        
    # 5. Salvataggio su Database
    matches_to_create = []
    
    # Coppie fisse
    for l, f in pairs:
        matches_to_create.append(Match(event=event, leader=l, follower=f, is_rotation=False))
        
    # Gestione esuberi (Rotazione in sala - Opzione B scelta dall'utente)
    for l in unmatched_leaders:
        matches_to_create.append(Match(event=event, leader=l, follower=None, is_rotation=True))
        
    for f in unmatched_followers:
        matches_to_create.append(Match(event=event, leader=None, follower=f, is_rotation=True))
        
    Match.objects.bulk_create(matches_to_create)
    
    return {
        "pairs_count": len(pairs),
        "rotating_leaders": len(unmatched_leaders),
        "rotating_followers": len(unmatched_followers)
    }
