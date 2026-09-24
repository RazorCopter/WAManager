import uuid
from django.db import models

class Role(models.TextChoices):
    LEADER = 'leader', 'Leader'
    FOLLOWER = 'follower', 'Follower'
    BOTH = 'both', 'Entrambi'

class Level(models.TextChoices):
    BEGINNER = 'beginner', 'Principiante'
    INTERMEDIATE = 'intermediate', 'Intermedio'
    ADVANCED = 'advanced', 'Avanzato'

class Gender(models.TextChoices):
    MALE = 'M', 'Uomo'
    FEMALE = 'F', 'Donna'

class Participant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone_number = models.CharField(max_length=20)
    gender = models.CharField(max_length=1, choices=Gender.choices, default=Gender.MALE)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.LEADER)
    level = models.CharField(max_length=20, choices=Level.choices, default=Level.INTERMEDIATE)
    is_active = models.BooleanField(default=True)
    privacy_accepted_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

class Event(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    date = models.DateField()
    time = models.TimeField()
    location = models.CharField(max_length=200)
    capacity_leaders = models.PositiveIntegerField(default=15)
    capacity_followers = models.PositiveIntegerField(default=15)
    whatsapp_group_name = models.CharField(max_length=200, default="Tango Catango", help_text="Nome esatto del gruppo WhatsApp in cui inviare i messaggi")
    rsvp_deadline = models.DateTimeField()
    
    # Scheduling campi
    rsvp_send_at = models.DateTimeField(null=True, blank=True, help_text="Data e ora in cui inviare il messaggio di apertura adesioni")
    rsvp_sent = models.BooleanField(default=False, help_text="Flag impostato a True quando il messaggio adesioni è stato inviato")
    
    match_send_at = models.DateTimeField(null=True, blank=True, help_text="Data e ora in cui inviare il messaggio con le coppie definitive")
    match_sent = models.BooleanField(default=False, help_text="Flag impostato a True quando le coppie sono state inviate")

    def __str__(self):
        return f"Event on {self.date} at {self.time}"

class AttendanceStatus(models.TextChoices):
    ATTENDING = 'attending', 'Presente'
    NOT_ATTENDING = 'not_attending', 'Assente'
    WAITLISTED = 'waitlisted', 'In Lista d\'Attesa'

class EventAttendance(models.Model):
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name='attendances')
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='attendances')
    status = models.CharField(max_length=20, choices=AttendanceStatus.choices, default=AttendanceStatus.ATTENDING)
    role_for_event = models.CharField(max_length=10, choices=Role.choices, null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('participant', 'event')

    def __str__(self):
        return f"{self.participant} - {self.event} ({self.get_status_display()})"

class MessageTemplate(models.Model):
    name = models.CharField(max_length=100)
    body = models.TextField(help_text="Testo con placeholder es. {{ event_date }}, {{ rsvp_link }}")
    
    def __str__(self):
        return self.name

class MessageLog(models.Model):
    event = models.ForeignKey(Event, on_delete=models.SET_NULL, null=True, blank=True)
    template = models.ForeignKey(MessageTemplate, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=50, default='Generato') # Generato, Inviato, Errore
    rendered_text = models.TextField()
    error_message = models.TextField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Log {self.id} - {self.status}"

class Match(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='matches')
    leader = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name='leader_matches', null=True, blank=True)
    follower = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name='follower_matches', null=True, blank=True)
    is_rotation = models.BooleanField(default=False, help_text="True se questa persona è in rotazione a causa di disparità numerica.")

    class Meta:
        verbose_name_plural = "Matches"

    def __str__(self):
        l_name = self.leader if self.leader else "Nessun Leader (Rotazione)"
        f_name = self.follower if self.follower else "Nessun Follower (Rotazione)"
        return f"{self.event.date}: {l_name} + {f_name}"

class RecurringSchedule(models.Model):
    days_of_week = models.CharField(max_length=50, default="0", help_text="Giorni della settimana (0=Lunedì, 6=Domenica) separati da virgola")
    time = models.TimeField(help_text="Ora in cui inizia l'evento")
    start_date = models.DateField(help_text="Data a partire dalla quale iniziare a schedulare", null=True, blank=True)
    end_date = models.DateField(help_text="Data fine schedulazione", null=True, blank=True)
    
    # Timing di invio sondaggio
    rsvp_days_before = models.IntegerField(default=0, help_text="Giorni prima dell'evento in cui inviare l'annuncio")
    rsvp_time = models.TimeField(default='08:00:00', help_text="Ora in cui inviare l'annuncio (es. mattina)")
    
    # Timing di invio coppie (Match)
    match_days_before = models.IntegerField(default=0, help_text="Quanti giorni prima dell'evento chiudere le adesioni e inviare le coppie")
    match_time = models.TimeField(default='19:00:00', help_text="Ora di chiusura adesioni e invio coppie")
    
    RSVP_MODE_CHOICES = [
        ('POLL', 'Sondaggio (Default)'),
        ('LLM', 'Risposta Libera (Gemini AI)'),
    ]
    rsvp_mode = models.CharField(max_length=10, choices=RSVP_MODE_CHOICES, default='POLL', help_text="Modalità di raccolta adesioni")
    
    gemini_api_key = models.CharField(max_length=255, blank=True, null=True, help_text="Chiave API per Google Gemini (Lettura Chat)")
    debug_mode = models.BooleanField(default=True, help_text="Mostra o nascondi i log delle attività")

    def __str__(self):
        return f"Giorni {self.days_of_week} alle {self.time}"
