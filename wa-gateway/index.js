process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';
const { default: makeWASocket, useMultiFileAuthState, DisconnectReason, getAggregateVotesInPollMessage, decryptPollVote } = require('@whiskeysockets/baileys');
const express = require('express');
const bodyParser = require('body-parser');
const axios = require('axios');
const cors = require('cors');
const fs = require('fs');
const pino = require('pino');
const qrcode = require('qrcode-terminal');
const qrcodeData = require('qrcode');

let globalSettings = { debugMode: false };

let currentStatus = 'INITIALIZING';
let currentQrDataUrl = null;

const app = express();
app.use(cors());
app.use(bodyParser.json());

const PORT = 4002;
const DJANGO_WEBHOOK_URL = 'http://127.0.0.1:8082/api/webhook/poll-vote/';

function logToFile(msg) {
    const logMsg = new Date().toISOString() + ' - ' + msg + '\n';
    fs.appendFileSync('gateway.log', logMsg);
    console.log(msg);
}

// Gestione manuale dei sondaggi in memoria per decifrare i voti senza usare makeInMemoryStore
const POLLS_FILE = './baileys_polls.json';
let sentPolls = {};
if (fs.existsSync(POLLS_FILE)) {
    try {
        sentPolls = JSON.parse(fs.readFileSync(POLLS_FILE, 'utf8'));
    } catch (e) {
        logToFile("Errore caricamento baileys_polls.json: " + e.message);
    }
}
function savePoll(msgId, messageObj) {
    sentPolls[msgId] = messageObj;
    fs.writeFileSync(POLLS_FILE, JSON.stringify(sentPolls, null, 2));
}

let sock = null;

async function connectToWhatsApp() {
    logToFile("Inizializzazione Baileys...");
    const { state, saveCreds } = await useMultiFileAuthState('baileys_auth_info');
    
    sock = makeWASocket({
        auth: state,
        printQRInTerminal: true,
        logger: pino({ level: "silent" }) // Disabilita i log prolissi di default
    });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect, qr } = update;
        if (qr) {
            logToFile('QR Code ricevuto, per favore scansionalo.');
            qrcode.generate(qr, { small: true });
            try {
                currentQrDataUrl = await qrcodeData.toDataURL(qr);
                currentStatus = 'QR';
            } catch (err) {
                console.error("Errore generazione QR image", err);
            }
        }
        if (connection === 'close') {
            const shouldReconnect = lastDisconnect.error?.output?.statusCode !== DisconnectReason.loggedOut;
            logToFile('Connessione chiusa. Motivo: ' + (lastDisconnect.error ? lastDisconnect.error.message : 'sconosciuto') + ' | Riconnessione: ' + shouldReconnect);
            currentStatus = 'DISCONNECTED';
            currentQrDataUrl = null;
            if (shouldReconnect) {
                setTimeout(connectToWhatsApp, 2000); // Wait a bit before reconnecting to avoid tight loops
            }
        } else if (connection === 'open') {
            logToFile('Client WhatsApp pronto! (Baileys)');
            currentStatus = 'CONNECTED';
            currentQrDataUrl = null;
        }
    });

    sock.ev.on('messages.upsert', async m => {
        for (const msg of m.messages) {
            if (!msg.message) continue;

            // 1. Gestione dei messaggi standard in arrivo
            const msgType = Object.keys(msg.message)[0];
            if (msgType === 'conversation' || msgType === 'extendedTextMessage') {
                const text = msg.message.conversation || msg.message.extendedTextMessage?.text;
                const sender = msg.key.participant || msg.key.remoteJid;
                
                // Filtra il parsing dei messaggi testuali solo al target group, per evitare log personali
                const targetGroup = process.env.TARGET_GROUP_ID;
                if (globalSettings.debugMode || (targetGroup && msg.key.remoteJid === targetGroup)) {
                    if (!msg.key.fromMe) {
                        logToFile(`Messaggio ricevuto: ${text} da ${sender}`);
                    } else {
                        logToFile(`Messaggio inviato (o dal bot): ${text} a ${msg.key.remoteJid}`);
                    }
                }
            }

            // 2. Gestione degli aggiornamenti ai SONDAGGI (Voti)
            if (msg.message.pollUpdateMessage) {
                try {
                    const pollCreationMsgKey = msg.message.pollUpdateMessage.pollCreationMessageKey;
                    const pollMsgId = pollCreationMsgKey.id;
                    const remoteJid = msg.key.remoteJid;

                    // Cerca il messaggio originale in memoria
                    const originalMsg = sentPolls[pollMsgId];
                    if (originalMsg) {
                        // Assicuriamoci che messageSecret sia un Buffer (potrebbe essere stato convertito in Base64 in JSON)
                        if (originalMsg.messageContextInfo && originalMsg.messageContextInfo.messageSecret) {
                            if (typeof originalMsg.messageContextInfo.messageSecret === 'string') {
                                originalMsg.messageContextInfo.messageSecret = Buffer.from(originalMsg.messageContextInfo.messageSecret, 'base64');
                            } else if (originalMsg.messageContextInfo.messageSecret.type === 'Buffer') {
                                originalMsg.messageContextInfo.messageSecret = Buffer.from(originalMsg.messageContextInfo.messageSecret.data);
                            }
                        }

                        const pollEncKey = originalMsg.messageContextInfo.messageSecret;
                        // Visto che salviamo solo i sondaggi inviati dal bot in sentPolls, il creator siamo sempre noi!
                        // WhatsApp Community bug: l'algoritmo di firma AES-GCM fallisce se il pollCreatorJid
                        // o il voterJid non matchano ESATTAMENTE quelli usati dal telefono per crittografare (JID vs LID).
                        const pollCreatorJids = [
                            sock.user.id.split(':')[0] + '@s.whatsapp.net',
                            sock.user.lid ? sock.user.lid.split(':')[0] + '@lid' : null,
                            msg.message.pollUpdateMessage.pollCreationMessageKey.participant
                        ].filter(Boolean);

                        const voterJids = [
                            msg.key.participant,
                            msg.key.remoteJid
                        ].filter(Boolean);

                        let dec = null;
                        let successCombo = null;

                        for (let creator of pollCreatorJids) {
                            for (let voter of voterJids) {
                                try {
                                    dec = decryptPollVote(msg.message.pollUpdateMessage.vote, {
                                        pollCreatorJid: creator,
                                        pollMsgId,
                                        pollEncKey,
                                        voterJid: voter
                                    });
                                    successCombo = { creator, voter };
                                    break;
                                } catch (err) { }
                            }
                            if (dec) break;
                        }

                        let selectedOptions = [];

                        if (!dec) {
                            logToFile(`DEBUG DECRYPT COMPLETELY FAILED per Utente: ${msg.key.participant || msg.key.remoteJid}. Tentati creator: ${pollCreatorJids}`);
                        } else {
                            logToFile(`DEBUG DECRYPT SUCCESS! Combo usata: ${JSON.stringify(successCombo)}`);
                            
                            // Abbiamo decrittato i voti (dec.selectedOptions contiene array di Uint8Array hash)
                            // Facciamo un manual map con gli hash SHA256 delle opzioni
                            const crypto = require('crypto');
                            const opts = originalMsg.pollCreationMessage?.options || [];
                            
                            for (const voteHash of dec.selectedOptions) {
                                const voteHashStr = Buffer.from(voteHash).toString('hex');
                                
                                for (const opt of opts) {
                                    const optHashBuffer = crypto.createHash('sha256').update(Buffer.from(opt.optionName || '')).digest();
                                    const optHashStr = optHashBuffer.toString('hex');
                                    
                                    if (voteHashStr === optHashStr) {
                                        selectedOptions.push(opt.optionName);
                                    }
                                }
                            }
                        }

                        // Risoluzione LID -> Numero di telefono (JID)
                        // In WhatsApp Communities, i voti arrivano con un @lid anonimo.
                        // Fortunatamente, i metadati del gruppo contengono la mappatura lid -> id!
                        const voterJid = msg.key.participant || msg.key.remoteJid;
                        let realSenderJid = voterJid;
                        try {
                            if (msg.key.remoteJid.endsWith('@g.us')) {
                                const groupMeta = await sock.groupMetadata(msg.key.remoteJid);
                                const p = groupMeta.participants.find(p => p.id === voterJid || p.lid === voterJid);
                                if (p) {
                                    logToFile(`DEBUG STRUTTURA PARTECIPANTE GRUPPO: ${JSON.stringify(p)}`);
                                    
                                    // Se c'è la proprietà phoneNumber o id senza @lid, usiamo quello!
                                    const actualNumber = p.phoneNumber ? p.phoneNumber : (p.id && !p.id.includes('@lid') ? p.id : null);
                                    
                                    if (actualNumber) {
                                        realSenderJid = actualNumber;
                                        logToFile(`LID Risolto in Numero Reale! ${voterJid} -> ${realSenderJid}`);
                                    } else {
                                        logToFile(`Attenzione: Il gruppo riporta il participant senza un numero reale: ${JSON.stringify(p)}`);
                                    }
                                } else {
                                    logToFile(`Attenzione: Utente ${voterJid} non trovato nei metadati del gruppo.`);
                                }
                            }
                        } catch (err) {
                            logToFile(`Errore recupero metadati gruppo per risolvere LID: ${err.message}`);
                        }

                        logToFile(`Voto sondaggio rilevato! Utente Reale: ${realSenderJid}, Scelte: ${JSON.stringify(selectedOptions)}`);

                        const payload = {
                            pollMessageId: pollMsgId,
                            voter: realSenderJid,
                            selectedOptions: selectedOptions,
                            action: 'vote_update'
                        };

                        try {
                            const response = await axios.post(DJANGO_WEBHOOK_URL, payload);
                            logToFile(`Webhook inviato per il voto di ${realSenderJid}. Risposta Django: ${JSON.stringify(response.data)}`);
                        } catch (webhookErr) {
                            logToFile(`Errore invio Webhook per ${realSenderJid}: ${webhookErr.message}`);
                        }
                    } else {
                        logToFile(`Messaggio sondaggio originale non trovato in memoria per ID: ${pollMsgId}. Impossibile decifrare il voto.`);
                    }
                } catch (err) {
                    logToFile("Errore poll update: " + err.message);
                }
            }
        }
    });
}

connectToWhatsApp();

// Endpoint API per aggiornare le impostazioni dal backend
app.post('/api/settings', (req, res) => {
    if (req.body.debug_mode !== undefined) {
        globalSettings.debugMode = req.body.debug_mode;
        logToFile(`Debug mode impostato a: ${globalSettings.debugMode}`);
    }
    res.json({ success: true, settings: globalSettings });
});

// Endpoint API per inviare messaggi (o sondaggi) dal backend
app.post('/api/send', async (req, res) => {
    const { to, message, isGroup, isPoll, pollOptions } = req.body;
    
    try {
        let chatId = to;
        if (isGroup && !chatId.endsWith('@g.us')) {
            chatId = `${to}@g.us`;
        } else if (!isGroup && !chatId.endsWith('@s.whatsapp.net')) {
            // Baileys usa s.whatsapp.net invece di c.us per i contatti
            chatId = `${to}@s.whatsapp.net`;
        }
        
        // Sostituzione per fallback se arriva c.us
        chatId = chatId.replace('@c.us', '@s.whatsapp.net');
        
        if (isPoll && pollOptions && pollOptions.length > 0) {
            logToFile(`Invio sondaggio a ${chatId}...`);
            const response = await sock.sendMessage(chatId, {
                poll: {
                    name: message,
                    values: pollOptions,
                    selectableCount: pollOptions.length // permise scelte multiple
                }
            });
            // Baileys restituisce un oggetto messaggio, prendiamo l'ID
            const msgId = response.key.id;
            // Salviamo il messaggio in memoria per decifrare i voti successivi
            savePoll(msgId, response.message);
            
            res.json({ success: true, response: { id: { _serialized: msgId } } }); // formato compatibile col vecchio
        } else {
            logToFile(`Invio messaggio testo a ${chatId}...`);
            const response = await sock.sendMessage(chatId, { text: message });
            const msgId = response.key.id;
            res.json({ success: true, response: { id: { _serialized: msgId } } });
        }
    } catch (error) {
        logToFile("Errore invio messaggio: " + error);
        res.status(500).json({ success: false, error: error.message || error });
    }
});

app.post('/api/logout', async (req, res) => {
    try {
        if (sock) {
            logToFile('Richiesta di logout WhatsApp ricevuta.');
            await sock.logout();
            sock = null;
            // connection.update handler will NOT reconnect automatically on explicit logout
            // We reconnect manually after a small delay to generate a new QR
            setTimeout(connectToWhatsApp, 3000);
        }
        res.json({ success: true, message: 'Account WhatsApp disconnesso.' });
    } catch (error) {
        logToFile("Errore logout: " + error);
        res.status(500).json({ success: false, error: error.message || error });
    }
});

app.listen(PORT, () => {
    console.log(`Gateway API in ascolto su porta ${PORT}`);
});

// Endpoint per stato connessione e QR
app.get('/api/status', (req, res) => {
    res.json({
        status: currentStatus,
        qr: currentQrDataUrl
    });
});
