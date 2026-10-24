import { test } from 'node:test'
import assert from 'node:assert/strict'
import http from 'node:http'

import { GatewayClient, GatewayError } from '../lib/gateway-client.js'

async function withServer(handler, run) {
  const server = http.createServer(handler)
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  const { port } = server.address()
  try {
    await run(`http://127.0.0.1:${port}`)
  } finally {
    await new Promise((resolve) => server.close(resolve))
  }
}

function readBody(request) {
  return new Promise((resolve, reject) => {
    let body = ''
    request.setEncoding('utf8')
    request.on('data', (chunk) => {
      body += chunk
    })
    request.on('end', () => resolve(body))
    request.on('error', reject)
  })
}

const activity = {
  id: 'act-1',
  matchKey: 'gomoku:gomoku-default',
  gameId: 'gomoku',
  gameName: '五子棋',
  matchId: 'gomoku-default',
  turnId: '12',
  actor: 'white',
  status: 'pending',
  display: 'board',
  instructions: 'place a stone',
  actionExample: { notation: 'H8' },
  state: { board: [] },
}

test('lists pending activations and fetches one', async () => {
  await withServer(async (request, response) => {
    if (request.url === '/api/activations?status=pending') {
      response.end(JSON.stringify({ ok: true, activations: [activity] }))
    } else if (request.url === '/api/activations/act-1') {
      response.end(JSON.stringify({ ok: true, activation: activity }))
    } else {
      response.statusCode = 404
      response.end(JSON.stringify({ ok: false, error: { code: 'not_found', message: 'nope' } }))
    }
  }, async (baseUrl) => {
    const client = new GatewayClient({ baseUrl })
    const pending = await client.pending()
    assert.equal(pending.length, 1)
    assert.equal(pending[0].id, 'act-1')
    const one = await client.activation('act-1')
    assert.equal(one.actor, 'white')
  })
})

test('submits actions as a JSON body', async () => {
  const bodies = []
  await withServer(async (request, response) => {
    bodies.push({ url: request.url, body: await readBody(request) })
    response.end(JSON.stringify({ ok: true, activation: { ...activity, status: 'acted' }, result: { display: 'done' } }))
  }, async (baseUrl) => {
    const client = new GatewayClient({ baseUrl })
    const result = await client.action('act-1', { notation: 'H8' })
    assert.equal(result.activation.status, 'acted')
    assert.equal(result.result.display, 'done')
  })
  assert.equal(bodies[0].url, '/api/activations/act-1/action')
  assert.deepEqual(JSON.parse(bodies[0].body), { action: { notation: 'H8' } })
})

test('matches and match detail endpoints', async () => {
  await withServer(async (request, response) => {
    if (request.url === '/api/matches') {
      response.end(JSON.stringify({ ok: true, matches: [{ key: 'gomoku:gomoku-default', matchId: 'gomoku-default' }] }))
    } else if (request.url === '/api/matches/gomoku%3Agomoku-default') {
      response.end(JSON.stringify({ ok: true, match: { key: 'gomoku:gomoku-default', display: 'board', state: {} } }))
    } else {
      response.statusCode = 404
      response.end(JSON.stringify({ ok: false, error: { code: 'not_found', message: 'nope' } }))
    }
  }, async (baseUrl) => {
    const client = new GatewayClient({ baseUrl })
    const matches = await client.matches()
    assert.equal(matches.length, 1)
    const detail = await client.matchDetail('gomoku:gomoku-default')
    assert.equal(detail.display, 'board')
  })
})

test('acks a result activation', async () => {
  const bodies = []
  await withServer(async (request, response) => {
    bodies.push({ url: request.url, body: await readBody(request) })
    response.end(JSON.stringify({ ok: true, activation: { ...activity, status: 'acked' } }))
  }, async (baseUrl) => {
    const client = new GatewayClient({ baseUrl })
    const result = await client.ack('act-1')
    assert.equal(result.activation.status, 'acked')
  })
  assert.equal(bodies[0].url, '/api/activations/act-1/ack')
  assert.deepEqual(JSON.parse(bodies[0].body), {})
})

test('exposes gateway errors', async () => {
  await withServer(async (request, response) => {
    await readBody(request)
    response.statusCode = 410
    response.end(JSON.stringify({ ok: false, error: { code: 'activation_closed', message: '已关闭' } }))
  }, async (baseUrl) => {
    const client = new GatewayClient({ baseUrl })
    await assert.rejects(
      () => client.action('act-1', {}),
      (error) => error instanceof GatewayError && error.code === 'activation_closed' && error.status === 410,
    )
  })
})

test('reports offline when the gateway is unreachable', async () => {
  const client = new GatewayClient({ baseUrl: 'http://127.0.0.1:9', timeoutMs: 200 })
  await assert.rejects(
    () => client.pending(),
    (error) => error instanceof GatewayError && error.code === 'offline',
  )
})
