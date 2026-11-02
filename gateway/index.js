// METATRON WhatsApp gateway: a linked device (like WhatsApp Web) on the broker's own number.
//
// Runs on the broker's computer next to the Python app and listens on 127.0.0.1 only.
//   GET  /status           connection state, own number, QR (data URL) while pairing
//   POST /connect          {mode: "qr"} or {mode: "phone", phone} -> pairing code
//   POST /send             {to, text, image?, typing_ms} -> {id}  (image: a local JPEG path;
//                          the text goes out as its caption, in one message)
//   POST /logout
// Every incoming 1:1 text message is forwarded to the app: POST $INBOUND_URL.
// Groups, status updates, newsletters and history sync are ignored.

import { createServer } from 'node:http'
import { readFile, rm } from 'node:fs/promises'
import makeWASocket, {
  Browsers, DisconnectReason, fetchLatestBaileysVersion, isJidGroup, isLidUser,
  jidNormalizedUser, useMultiFileAuthState,
} from 'baileys'
import pino from 'pino'
import QRCode from 'qrcode'

const PORT = Number(process.env.GATEWAY_PORT || 8766)
const TOKEN = process.env.GATEWAY_TOKEN || ''
const AUTH_DIR = process.env.WA_AUTH_DIR || './wa-auth'
const INBOUND_URL = process.env.INBOUND_URL || 'http://127.0.0.1:8765/internal/wa/inbound'
const logger = pino({ level: process.env.GATEWAY_LOG_LEVEL || 'warn' })

const state = { status: 'disconnected', qr: null, pairingCode: null, me: null, error: null }
let sock = null
let pairPhone = null
let retries = 0

const digits = (s) => String(s || '').replace(/\D/g, '')
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function phoneOf(jid, alt) {
  // WhatsApp now addresses many chats by LID; the app matches sellers by phone number.
  if (alt && !isLidUser(alt)) return digits(jidNormalizedUser(alt).split('@')[0])
  if (isLidUser(jid)) {
    const pn = await sock?.signalRepository?.lidMapping?.getPNForLID(jid)
    return pn ? digits(pn.split('@')[0].split(':')[0]) : null
  }
  return digits(jidNormalizedUser(jid).split('@')[0])
}

function textOf(m) {
  const msg = m.message || {}
  return msg.conversation || msg.extendedTextMessage?.text || msg.imageMessage?.caption ||
    msg.videoMessage?.caption || msg.buttonsResponseMessage?.selectedDisplayText ||
    msg.listResponseMessage?.title || ''
}

async function forward(m) {
  const jid = m.key.remoteJid || ''
  if (!jid || isJidGroup(jid) || jid === 'status@broadcast' || jid.endsWith('@newsletter')) return
  const text = textOf(m).trim()
  if (!text) return
  const phone = await phoneOf(jid, m.key.remoteJidAlt)
  if (!phone) return
  const body = {
    id: m.key.id, phone, text, from_me: Boolean(m.key.fromMe),
    push_name: m.pushName || null, ts: Number(m.messageTimestamp || 0),
  }
  for (let i = 0; i < 5; i++) {
    try {
      const r = await fetch(INBOUND_URL, {
        method: 'POST',
        headers: { 'content-type': 'application/json', 'x-gateway-token': TOKEN },
        body: JSON.stringify(body),
      })
      if (r.ok) return
    } catch (e) { logger.warn({ err: String(e) }, 'inbound forward failed') }
    await sleep(1000 * 2 ** i)
  }
}

async function start() {
  const { state: auth, saveCreds } = await useMultiFileAuthState(AUTH_DIR)
  const { version } = await fetchLatestBaileysVersion().catch(() => ({ version: undefined }))
  state.status = 'connecting'
  state.error = null
  sock = makeWASocket({
    auth, version, logger,
    // Must be a browser WhatsApp knows: with an unknown name ("METATRON") the phone rejects the
    // 8-character pairing code. Shown in the phone's linked devices as "Chrome (Windows)".
    browser: Browsers.windows('Chrome'),
    markOnlineOnConnect: false, // the broker's phone keeps getting notifications
    syncFullHistory: false,
    emitOwnEvents: false, // our own sends are not echoed back as "typed on the phone"
  })
  sock.ev.on('creds.update', saveCreds)
  sock.ev.on('connection.update', async (u) => {
    if (u.qr) {
      if (pairPhone && !auth.creds.registered && !state.pairingCode) {
        try {
          state.pairingCode = await sock.requestPairingCode(pairPhone)
          state.status = 'pairing'
        } catch (e) { state.error = `pairing failed: ${e}` }
      } else if (!pairPhone) {
        state.qr = await QRCode.toDataURL(u.qr, { margin: 1, width: 320 })
        state.status = 'qr'
      }
    }
    if (u.connection === 'open') {
      retries = 0
      Object.assign(state, { status: 'open', qr: null, pairingCode: null, error: null })
      pairPhone = null
      state.me = { phone: digits(sock.user?.id?.split(':')[0]), name: sock.user?.name || null }
    }
    if (u.connection === 'close') {
      const code = u.lastDisconnect?.error?.output?.statusCode
      sock = null
      if (code === DisconnectReason.loggedOut) {
        await rm(AUTH_DIR, { recursive: true, force: true })
        Object.assign(state, { status: 'logged_out', qr: null, pairingCode: null, me: null })
        return
      }
      // Not linked yet and the code/QR ran out (WhatsApp closes after ~3 minutes): say so, so
      // the dashboard offers a fresh code instead of showing a dead one.
      if (code !== DisconnectReason.restartRequired && !auth.creds.registered) {
        Object.assign(state, { status: 'expired', qr: null, pairingCode: null })
        pairPhone = null
        return
      }
      // restartRequired comes right after pairing; anything else: back off and retry
      state.status = 'reconnecting'
      const wait = code === DisconnectReason.restartRequired ? 0 : Math.min(60000, 2000 * 2 ** retries++)
      setTimeout(() => start().catch(fail), wait)
    }
  })
  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify' && type !== 'append') return
    for (const m of messages) await forward(m).catch((e) => logger.warn({ err: String(e) }))
  })
}

function fail(e) {
  state.status = 'error'
  state.error = String(e)
  logger.error({ err: String(e) }, 'gateway error')
}

async function send(to, text, typingMs, image) {
  if (!sock || state.status !== 'open') throw new Error('whatsapp is not connected')
  const jid = `${digits(to)}@s.whatsapp.net`
  const [found] = await sock.onWhatsApp(jid)
  if (!found?.exists) throw new Error('number is not on WhatsApp')
  if (typingMs > 0) { // look like a person typing, not a burst
    await sock.presenceSubscribe(found.jid).catch(() => {})
    await sock.sendPresenceUpdate('composing', found.jid).catch(() => {})
    await sleep(Math.min(typingMs, 15000))
    await sock.sendPresenceUpdate('paused', found.jid).catch(() => {})
  }
  const content = image
    ? { image: await readFile(image), mimetype: 'image/jpeg', caption: text }
    : { text }
  const res = await sock.sendMessage(found.jid, content)
  return res?.key?.id || null
}

async function readJson(req) {
  let raw = ''
  for await (const chunk of req) raw += chunk
  return raw ? JSON.parse(raw) : {}
}

function reply(res, code, body) {
  res.writeHead(code, { 'content-type': 'application/json' })
  res.end(JSON.stringify(body))
}

createServer(async (req, res) => {
  if (TOKEN && req.headers['x-gateway-token'] !== TOKEN) return reply(res, 401, { error: 'unauthorized' })
  try {
    if (req.method === 'GET' && req.url === '/status') return reply(res, 200, state)
    if (req.method === 'POST' && req.url === '/connect') {
      const { mode, phone } = await readJson(req)
      if (state.status === 'open') return reply(res, 200, state)
      pairPhone = mode === 'phone' ? digits(phone).replace(/^0/, '972') : null
      if (mode === 'phone' && pairPhone.length < 11) return reply(res, 400, { error: 'invalid phone number' })
      Object.assign(state, { qr: null, pairingCode: null })
      if (sock) { sock.end(undefined); sock = null }
      await rm(AUTH_DIR, { recursive: true, force: true }) // a fresh link every time
      await start()
      for (let i = 0; i < 40 && !state.qr && !state.pairingCode && !state.error; i++) await sleep(250)
      return reply(res, 200, state)
    }
    if (req.method === 'POST' && req.url === '/send') {
      const { to, text, image, typing_ms: typingMs = 0 } = await readJson(req)
      return reply(res, 200, { id: await send(to, text, Number(typingMs), image || null) })
    }
    if (req.method === 'POST' && req.url === '/logout') {
      if (sock) await sock.logout().catch(() => {})
      await rm(AUTH_DIR, { recursive: true, force: true })
      Object.assign(state, { status: 'logged_out', qr: null, pairingCode: null, me: null })
      return reply(res, 200, state)
    }
    reply(res, 404, { error: 'not found' })
  } catch (e) {
    reply(res, 500, { error: String(e.message || e) })
  }
}).listen(PORT, '127.0.0.1', async () => {
  // Exit with the app: if METATRON is killed, no orphan gateway keeps the WhatsApp link busy.
  const parent = Number(process.env.PARENT_PID || 0)
  if (parent) {
    setInterval(() => {
      try { process.kill(parent, 0) } catch { process.exit(0) }
    }, 5000)
  }
  logger.info(`gateway on 127.0.0.1:${PORT}`)
  // Already linked on an earlier run: reconnect silently.
  const { state: auth } = await useMultiFileAuthState(AUTH_DIR)
  if (auth.creds.registered) start().catch(fail)
})
