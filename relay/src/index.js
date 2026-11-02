// METATRON relay: forwards the app's Claude calls with the server-side API key.
// Each broker has a license key; requests are limited per license per day and to known models.

const MODELS = new Set(['claude-sonnet-5-5', 'claude-haiku-5-5'])
const MAX_TOKENS = 1000

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })

export default {
  async fetch(request, env) {
    const url = new URL(request.url)
    if (url.pathname === '/health') return json({ ok: true })
    if (url.pathname !== '/v1/messages' || request.method !== 'POST') return json({ error: 'not found' }, 404)

    const key = (request.headers.get('authorization') || '').replace(/^Bearer\s+/i, '')
    const license = key && (await env.LICENSES.get(key, 'json'))
    if (!license || !license.active) return json({ error: 'invalid license' }, 401)

    const day = new Date().toISOString().slice(0, 10)
    const usageKey = `usage:${key}:${day}`
    const used = Number((await env.LICENSES.get(usageKey)) || 0)
    if (used >= (license.daily_limit || 300)) return json({ error: 'daily limit reached' }, 429)

    let body
    try { body = await request.json() } catch { return json({ error: 'bad json' }, 400) }
    if (!MODELS.has(body.model)) return json({ error: 'model not allowed' }, 400)
    const payload = {
      model: body.model,
      max_tokens: Math.min(Number(body.max_tokens) || 600, MAX_TOKENS),
      temperature: body.temperature ?? 0.2,
      messages: body.messages,
      ...(body.system ? { system: body.system } : {}),
    }
    const r = await fetch('https://api.anthropic.com/v1/messages', {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-api-key': env.ANTHROPIC_API_KEY,
        'anthropic-version': '2023-06-01',
      },
      body: JSON.stringify(payload),
    })
    await env.LICENSES.put(usageKey, String(used + 1), { expirationTtl: 60 * 60 * 48 })
    return new Response(r.body, { status: r.status, headers: { 'content-type': 'application/json' } })
  },
}
