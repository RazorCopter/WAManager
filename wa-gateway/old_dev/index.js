const { Client, LocalAuth, Poll } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const express = require('express');
const bodyParser = require('body-parser');
const axios = require('axios');
const cors = require('cors');

const app = express();
app.use(cors());
app.use(bodyParser.json());

const PORT = 4002;
const DJANGO_WEBHOOK_URL = 'http://127.0.0.1:8082/api/webhook/poll-vote/';

const fs = require('fs');
function logToFile(msg) {
    fs.appendFileSync('gateway.log', new Date().toISOString() + ' - ' + msg + '\n');
    console.log(msg);
}

// Inizializza il client WhatsApp
const client = new Client({
    authStrategy: new LocalAuth(),
    puppeteer: { 
        headless: true,
        executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
        args: ['--no-sandbox', '--disable-setuid-sandbox']
    }
});

client.on('qr', (qr) => {
    console.log('Scansiona questo QR Code con WhatsApp:');
    qrcode.generate(qr, { small: true });
});

client.on('ready', () => {
    console.log('Client WhatsApp pronto!');
});

// Ascolta i voti ai sondaggi in arrivo
client.on('vote_update', async (vote) => {
    try {
        logToFile('Voto ricevuto! ' + JSON.stringify(vote));
        
        // Recuperiamo il messaggio padre originale se le opzioni sono undefined (problema noto di whatsapp-web.js quando il msg non è in cache)
        let parentMsg = vote.parentMessage;
        let selectedOptions = (vote.selectedOptions || []).map(opt => opt?.name);
        
        if (selectedOptions.includes(undefined)) {
            console.log("Opzioni sondaggio undefined, provo a recuperare il messaggio padre originale...");
            try {
                if (vote.parentMsgKey && vote.parentMsgKey._serialized) {
                    parentMsg = await client.getMessageById(vote.parentMsgKey._serialized);
                    if (parentMsg && parentMsg.pollOptions) {
                        selectedOptions = vote.selectedOptions.map(opt => {
                            const found = parentMsg.pollOptions.find(po => po.localId === opt.localId);
                            return found ? found.name : undefined;
                        });
                    }
                }
            } catch (err) {
                console.error("Errore nel recupero del messaggio sondaggio originale:", err.message);
            }
        }
        
        // Filtriamo eventuali undefined rimasti
        selectedOptions = selectedOptions.filter(name => name !== undefined && name !== null);
        
        // Estrai il numero di telefono del votante
        const voter = vote.voter;
        
        logToFile(`L'utente ${voter} ha votato: ${selectedOptions.join(', ')}`);
        
        // Inoltra il voto al server Django
        await axios.post(DJANGO_WEBHOOK_URL, {
            voter: voter,
            selectedOptions: selectedOptions,
            pollMessageId: vote.parentMessage?.id?._serialized || vote.parentMsgKey?._serialized || ""
        });
        logToFile(`Inoltrato voto a Django per ${voter}`);
        
    } catch (error) {
        logToFile("Errore durante l'inoltro del voto a Django: " + error.message);
    }
});

client.on('message', async (msg) => {
    logToFile(`Messaggio ricevuto: ${msg.body} da ${msg.from}`);
});

client.on('message_create', async (msg) => {
    if (msg.fromMe) {
        logToFile(`Messaggio inviato (o dal bot): ${msg.body} a ${msg.to}`);
    }
});

// Endpoint API per inviare messaggi (o sondaggi) dal backend
app.post('/api/send', async (req, res) => {
    const { to, message, isGroup, isPoll, pollOptions } = req.body;
    
    try {
        let chatId = to;
        if (isGroup && !chatId.endsWith('@g.us')) {
            chatId = `${to}@g.us`;
        } else if (!isGroup && !chatId.endsWith('@c.us')) {
            chatId = `${to}@c.us`;
        }
        
        if (isPoll && pollOptions && pollOptions.length > 0) {
            logToFile(`Invio sondaggio a ${chatId}...`);
            const poll = new Poll(message, pollOptions);
            const response = await client.sendMessage(chatId, poll);
            res.json({ success: true, response });
        } else {
            logToFile(`Invio messaggio testo a ${chatId}...`);
            const response = await client.sendMessage(chatId, message);
            res.json({ success: true, response });
        }
    } catch (err) {
        console.error("Errore invio messaggio:", err);
        res.status(500).json({ success: false, error: err.toString() });
    }
});

// Avvia Web Server e WhatsApp Client
app.get('/api/poll-votes', async (req, res) => {
    const { chatId } = req.query;
    try {
        const chat = await client.getChatById(chatId);
        const msgs = await chat.fetchMessages({ limit: 20 });
        let pollMsg = msgs.reverse().find(m => m.type === 'poll_creation');
        
        if (!pollMsg) {
            return res.json({ success: false, error: 'Nessun sondaggio trovato' });
        }
        
        // Voti sono in pollMsg.pollVotes
        res.json({ success: true, pollVotes: pollMsg.pollVotes, pollMessageId: pollMsg.id._serialized });
    } catch (error) {
        logToFile("Errore fetch voti: " + error.stack);
        res.status(500).json({ success: false, error: error.stack });
    }
});

app.listen(PORT, () => {
    console.log(`Gateway API in ascolto su porta ${PORT}`);
});

client.initialize();
