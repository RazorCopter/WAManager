import os
import requests
from django.conf import settings
from .models import MessageLog

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:4002/api/send")

def send_whatsapp_message(to: str, message: str, is_group: bool = True, is_poll: bool = False, poll_options: list = None) -> dict:
    """
    Invia un messaggio o sondaggio a WhatsApp tramite il gateway Node.js locale.
    """
    if poll_options is None:
        poll_options = []
        
    payload = {
        "to": to,
        "message": message,
        "isGroup": is_group,
        "isPoll": is_poll,
        "pollOptions": poll_options
    }
    
    try:
        response = requests.post(GATEWAY_URL, json=payload, timeout=15)
        response.raise_for_status()
        return {"success": True, "response": response.json()}
    except requests.exceptions.RequestException as e:
        print(f"Errore di comunicazione col Gateway WhatsApp: {e}")
        return {"success": False, "error": str(e)}
