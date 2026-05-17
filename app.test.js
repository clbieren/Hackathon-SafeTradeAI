const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const appPath = path.join(__dirname, 'app.js');
const appSource = fs.readFileSync(appPath, 'utf8');

function escapeHtml(value) {
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

class FakeElement {
  constructor(tagName, id = null) {
    this.tagName = String(tagName || 'div').toUpperCase();
    this.id = id;
    this.value = '';
    this.disabled = false;
    this.textContent = '';
    this.innerText = '';
    this.className = '';
    this.children = [];
    this.attributes = {};
    this.style = {};
    this.listeners = {};
    this.scrollTop = 0;
    this.scrollHeight = 100;
    this._innerHTML = '';
  }

  set innerHTML(value) {
    this._innerHTML = String(value);
    this.children = [];
    const optionRegex = /<option[^>]*value="([^"]*)"[^>]*>([^<]*)<\/option>/g;
    let match = optionRegex.exec(this._innerHTML);
    while (match) {
      const option = new FakeElement('option');
      option.value = match[1];
      option.textContent = match[2];
      option.innerText = match[2];
      this.children.push(option);
      match = optionRegex.exec(this._innerHTML);
    }
  }

  get innerHTML() {
    if (this.children.length === 0) {
      return this._innerHTML;
    }
    if (this.tagName === 'SELECT') {
      const rendered = this.children
        .map((child) => `<option value="${child.value}">${child.textContent || ''}</option>`)
        .join('');
      return this._innerHTML + rendered;
    }
    const rendered = this.children
      .map((child) => {
        if (child.nodeType === 3) return escapeHtml(child.textContent);
        return `<${child.tagName.toLowerCase()}>${child.innerHTML || child.textContent || ''}</${child.tagName.toLowerCase()}>`;
      })
      .join('');
    return rendered;
  }

  get options() {
    return this.children.filter((child) => child.tagName === 'OPTION');
  }

  appendChild(child) {
    this.children.push(child);
    return child;
  }

  addEventListener(type, handler) {
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(handler);
  }

  dispatchEvent(event) {
    const handlers = this.listeners[event.type] || [];
    for (const handler of handlers) {
      handler.call(this, event);
    }
    return true;
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
  }

  getAttribute(name) {
    return this.attributes[name] || null;
  }
}

class FakeDocument {
  constructor(html) {
    this.elements = {};
    this.listeners = {};
    this._parse(html);
  }

  _parse(html) {
    const tagRegex = /<([a-zA-Z0-9]+)([^>]*)>/g;
    let match = tagRegex.exec(html);
    while (match) {
      const tagName = match[1].toLowerCase();
      const attrs = match[2];
      const idMatch = attrs.match(/id="([^"]+)"/);
      if (!idMatch) {
        match = tagRegex.exec(html);
        continue;
      }

      const element = new FakeElement(tagName, idMatch[1]);
      const valueMatch = attrs.match(/value="([^"]*)"/);
      if (valueMatch) element.value = valueMatch[1];
      const styleMatch = attrs.match(/style="([^"]*)"/);
      if (styleMatch) {
        for (const stylePart of styleMatch[1].split(';')) {
          const [k, v] = stylePart.split(':');
          if (k && v) element.style[k.trim()] = v.trim();
        }
      }
      this.elements[element.id] = element;
      match = tagRegex.exec(html);
    }
  }

  getElementById(id) {
    return this.elements[id] || null;
  }

  createElement(tagName) {
    return new FakeElement(tagName);
  }

  createTextNode(text) {
    return {
      nodeType: 3,
      textContent: String(text),
    };
  }

  addEventListener(type, handler) {
    if (!this.listeners[type]) this.listeners[type] = [];
    this.listeners[type].push(handler);
  }

  dispatchEvent(event) {
    const handlers = this.listeners[event.type] || [];
    for (const handler of handlers) {
      handler.call(this, event);
    }
  }
}

class FakeStorage {
  constructor() {
    this.store = new Map();
  }
  setItem(key, value) {
    this.store.set(key, String(value));
  }
  getItem(key) {
    return this.store.has(key) ? this.store.get(key) : null;
  }
}

function createFetchResponse({ ok = true, jsonData = {}, readerChunks = null }) {
  if (readerChunks) {
    let index = 0;
    return {
      ok,
      json: async () => jsonData,
      body: {
        getReader() {
          return {
            async read() {
              if (index >= readerChunks.length) {
                return { value: undefined, done: true };
              }
              const value = readerChunks[index++];
              return { value, done: false };
            },
          };
        },
      },
    };
  }

  return {
    ok,
    json: async () => jsonData,
    body: {
      getReader() {
        return {
          async read() {
            return { value: undefined, done: true };
          },
        };
      },
    },
  };
}

function setupApp(html, { pathname = '/discovery.html' } = {}) {
  const document = new FakeDocument(html);
  const location = {
    protocol: 'http:',
    pathname,
    href: `http://localhost${pathname}`,
  };
  const windowObj = {
    document,
    navigator: {},
    location,
    Event: function Event(type) {
      this.type = type;
      this.target = null;
    },
  };
  const context = {
    window: windowObj,
    document,
    navigator: {},
    localStorage: new FakeStorage(),
    TextDecoder,
    console,
    fetch: async () => {
      throw new Error('fetch mock not set');
    },
    lucide: { createIcons: () => {} },
    alert: () => {},
    encodeURIComponent,
    setTimeout,
    clearTimeout,
  };

  context.window.fetch = (...args) => context.fetch(...args);
  context.window.localStorage = context.localStorage;
  context.window.lucide = context.lucide;
  context.window.alert = (...args) => context.alert(...args);
  context.window.TextDecoder = TextDecoder;
  context.window.console = context.console;

  vm.createContext(context);
  vm.runInContext(appSource, context, { filename: 'app.js' });

  return context;
}

test('loadProvinces sorts provinces and binds change listener', async () => {
  const ctx = setupApp(`
    <select id="citySelect"></select>
    <select id="districtSelect"></select>
  `);

  const provinces = [
    { name: 'İzmir', districts: [{ name: 'Bornova' }] },
    { name: 'Ankara', districts: [{ name: 'Çankaya' }] },
  ];

  let calledUrl = '';
  ctx.fetch = async (url) => {
    calledUrl = url;
    return createFetchResponse({
      jsonData: { status: 'OK', data: provinces },
    });
  };

  ctx.loadDistricts = (name) => {
    const districtSelect = ctx.document.getElementById('districtSelect');
    districtSelect.setAttribute('data-selected-city', name);
  };

  await ctx.loadProvinces();

  const citySelect = ctx.document.getElementById('citySelect');
  assert.equal(calledUrl, 'https://turkiyeapi.dev/api/v1/provinces');
  assert.equal(citySelect.options.length, 3);
  assert.equal(citySelect.options[1].value, 'Ankara');
  assert.equal(citySelect.options[2].value, 'İzmir');

  citySelect.value = 'Ankara';
  const event = new ctx.window.Event('change');
  event.target = citySelect;
  citySelect.dispatchEvent(event);

  const districtSelect = ctx.document.getElementById('districtSelect');
  assert.equal(districtSelect.getAttribute('data-selected-city'), 'Ankara');
});

test('loadProvinces handles fetch error without throwing', async () => {
  const ctx = setupApp(`<select id="citySelect"></select>`);
  let logged = false;
  ctx.console = {
    ...console,
    error: (...args) => {
      if (String(args[0]).includes('Türkiye API hatası')) logged = true;
    },
  };
  ctx.window.console = ctx.console;
  ctx.fetch = async () => {
    throw new Error('network');
  };

  await ctx.loadProvinces();
  assert.equal(logged, true);
});

test('loadDistricts handles empty province and unknown province', async () => {
  const ctx = setupApp(`
    <select id="citySelect"></select>
    <select id="districtSelect"></select>
  `);

  ctx.fetch = async () =>
    createFetchResponse({
      jsonData: {
        status: 'OK',
        data: [{ name: 'Adana', districts: [{ name: 'Seyhan' }, { name: 'Aladağ' }] }],
      },
    });
  await ctx.loadProvinces();

  const districtSelect = ctx.document.getElementById('districtSelect');
  ctx.loadDistricts('');
  assert.equal(districtSelect.disabled, true);
  assert.match(districtSelect.innerHTML, /Önce İl Seçiniz/);

  const previousHtml = districtSelect.innerHTML;
  ctx.loadDistricts('NotARealCity');
  assert.equal(districtSelect.innerHTML, previousHtml);
});

test('fetchDiscoverResults renders loading, cards, and restores button state', async () => {
  const ctx = setupApp(`
    <input id="qInput" value="metal" />
    <select id="citySelect"><option value="Ankara" selected>Ankara</option></select>
    <select id="districtSelect"><option value="Çankaya" selected>Çankaya</option></select>
    <button id="searchBtn"></button>
    <div id="resultsList"></div>
  `);

  let capturedUrl = '';
  let iconsCalled = 0;
  ctx.lucide = { createIcons: () => { iconsCalled += 1; } };
  ctx.window.lucide = ctx.lucide;
  ctx.fetch = async (url) => {
    capturedUrl = url;
    return createFetchResponse({
      ok: true,
      jsonData: {
        results: [
          {
            id: 3,
            name: 'Acme <img src=x onerror=alert(1)> Ltd',
            tax_number: null,
            address: '',
            report: { trust_score: 74.2 },
          },
        ],
      },
    });
  };

  const searchBtn = ctx.document.getElementById('searchBtn');
  const results = ctx.document.getElementById('resultsList');
  ctx.document.getElementById('citySelect').value = 'Ankara';
  ctx.document.getElementById('districtSelect').value = 'Çankaya';
  const pending = ctx.fetchDiscoverResults();
  assert.equal(searchBtn.disabled, true);
  assert.match(results.innerHTML, /İSTİHBARAT TOPLANIYOR/);
  await pending;

  assert.match(capturedUrl, /\/discover\?/);
  assert.match(capturedUrl, /q=metal/);
  assert.match(capturedUrl, /city=Ankara/);
  assert.match(capturedUrl, /district=%C3%87ankaya/);
  assert.equal(searchBtn.disabled, false);
  assert.equal(results.children.length, 1);
  assert.match(results.children[0].innerHTML, /Acme &lt;img src=x onerror=alert\(1\)&gt; Ltd/);
  assert.match(results.children[0].innerHTML, /74/);
  assert.doesNotMatch(results.children[0].innerHTML, /<img src=x/);
  assert.equal(iconsCalled, 1);
});

test('fetchDiscoverResults handles API failure and empty results', async () => {
  const ctx = setupApp(`
    <input id="qInput" value="" />
    <select id="citySelect"><option value=""></option></select>
    <select id="districtSelect"><option value=""></option></select>
    <button id="searchBtn"></button>
    <div id="resultsList"></div>
  `);

  const results = ctx.document.getElementById('resultsList');
  ctx.fetch = async () => createFetchResponse({ ok: true, jsonData: { results: [] } });
  await ctx.fetchDiscoverResults();
  assert.match(results.innerHTML, /Sonuç bulunamadı/);

  ctx.fetch = async () => createFetchResponse({ ok: false, jsonData: {} });
  await ctx.fetchDiscoverResults();
  assert.match(results.innerHTML, /Hata: API hatası/);
  assert.equal(ctx.document.getElementById('searchBtn').disabled, false);

  ctx.fetch = async () => {
    throw new Error('<img src=x onerror=alert(1)>');
  };
  await ctx.fetchDiscoverResults();
  assert.doesNotMatch(results.innerHTML, /<img src=x/);
});

test('startDeepAnalysis streams status, chunk, and result events', async () => {
  const ctx = setupApp(`
    <div id="reportContent" style="display:none"></div>
    <div id="reportLoading" style="display:block"></div>
    <pre id="streamView"></pre>
    <span id="reportStatus"></span>
    <h1 id="reportCompanyName"></h1>
    <div id="reportMeta"></div>
    <div id="genelSkor"></div>
    <div id="riskSummary"></div>
    <div id="kaliteSkor"></div>
    <div id="memnuniyetSkor"></div>
    <div id="yonetisimSkor"></div>
    <div id="decisionBadge"></div>
    <ul id="gucluYonler"></ul>
    <ul id="temelRiskler"></ul>
    <ul id="oneriler"></ul>
    <div id="sicilDetay"></div>
  `, { pathname: '/report.html' });

  let iconsCalled = 0;
  ctx.lucide = { createIcons: () => { iconsCalled += 1; } };
  ctx.window.lucide = ctx.lucide;

  const encoder = new TextEncoder();
  const sse = [
    'data: {"type":"status","message":"processing"}\n',
    'data: {"type":"chunk","text":"ilk bölüm"}\n',
    'data: {"type":"result","data":{"genel_skor":80,"risk_summary":"OK","kalite_skoru":88,"musteri_memnuniyeti_skoru":90,"operasyon_ve_yonetisim_skoru":77,"tedarikci_karari":"DEVAM","guclu_yonler":["Hız"],"kirmizi_bayraklar":[],"ne_yapmali":["Sürdür"],"resmi_sicil_detaylari":"Temiz"}}\n',
    'data: [DONE]\n',
  ].map((chunk) => encoder.encode(chunk));

  ctx.fetch = async () => createFetchResponse({ readerChunks: sse });
  await ctx.startDeepAnalysis(9, 'Mega Corp');

  assert.equal(ctx.document.getElementById('reportCompanyName').innerText, 'Mega Corp');
  assert.match(ctx.document.getElementById('reportMeta').innerText, /ID: 9/);
  assert.equal(ctx.document.getElementById('reportStatus').innerText, 'PROCESSING');
  assert.match(ctx.document.getElementById('streamView').textContent, /ilk bölüm/);
  assert.equal(ctx.document.getElementById('reportLoading').style.display, 'none');
  assert.equal(ctx.document.getElementById('reportContent').style.display, 'block');
  assert.equal(ctx.document.getElementById('genelSkor').innerText, 80);
  assert.equal(iconsCalled, 1);
});

test('startDeepAnalysis tolerates heartbeat and malformed payload', async () => {
  const ctx = setupApp(`
    <div id="reportContent" style="display:none"></div>
    <div id="reportLoading" style="display:block"></div>
    <pre id="streamView"></pre>
    <span id="reportStatus"></span>
    <h1 id="reportCompanyName"></h1>
    <div id="reportMeta"></div>
    <div id="genelSkor"></div>
    <div id="riskSummary"></div>
    <div id="kaliteSkor"></div>
    <div id="memnuniyetSkor"></div>
    <div id="yonetisimSkor"></div>
    <div id="decisionBadge"></div>
    <ul id="gucluYonler"></ul>
    <ul id="temelRiskler"></ul>
    <ul id="oneriler"></ul>
    <div id="sicilDetay"></div>
  `, { pathname: '/report.html' });

  const encoder = new TextEncoder();
  const sse = [
    'data: {"type":"heartbeat","ts":123}\n',
    'data: {"type":"chunk","text":"abc"}\n',
    'data: {broken json\n',
    'data: {"type":"result","data":{"genel_skor":60,"risk_summary":"ok","kalite_skoru":60,"musteri_memnuniyeti_skoru":60,"operasyon_ve_yonetisim_skoru":60,"tedarikci_karari":"DEVAM","guclu_yonler":[],"kirmizi_bayraklar":[],"ne_yapmali":[],"resmi_sicil_detaylari":""}}\n',
    'data: [DONE]\n',
  ].map((chunk) => encoder.encode(chunk));
  ctx.fetch = async () => createFetchResponse({ readerChunks: sse });
  await ctx.startDeepAnalysis(2, 'Heartbeat Co');
  assert.equal(ctx.document.getElementById('genelSkor').innerText, 60);
});

test('startDeepAnalysis catches stream failure gracefully', async () => {
  const ctx = setupApp(`
    <div id="reportContent"></div>
    <div id="reportLoading"></div>
    <pre id="streamView"></pre>
    <span id="reportStatus"></span>
    <h1 id="reportCompanyName"></h1>
    <div id="reportMeta"></div>
  `, { pathname: '/report.html' });

  let logged = false;
  ctx.console = {
    ...console,
    error: (...args) => {
      if (String(args[0]).includes('Analysis error')) logged = true;
    },
  };
  ctx.window.console = ctx.console;
  ctx.fetch = async () => {
    throw new Error('stream disconnected');
  };

  await ctx.startDeepAnalysis(5, 'Failing Co');
  assert.equal(logged, true);
  assert.equal(ctx.document.getElementById('reportStatus').innerText, 'HATA');
});

test('_renderReportData applies defaults and decision color boundaries', () => {
  const ctx = setupApp(`
    <div id="genelSkor"></div>
    <div id="riskSummary"></div>
    <div id="kaliteSkor"></div>
    <div id="memnuniyetSkor"></div>
    <div id="yonetisimSkor"></div>
    <div id="decisionBadge"></div>
    <ul id="gucluYonler"></ul>
    <ul id="temelRiskler"></ul>
    <ul id="oneriler"></ul>
    <div id="sicilDetay"></div>
  `, { pathname: '/report.html' });

  ctx._renderReportData({
    genel_skor: 35,
    risk_summary: '',
    tedarikci_karari: 'DUR',
    guclu_yonler: null,
    kirmizi_bayraklar: null,
    ne_yapmali: null,
  });

  assert.equal(ctx.document.getElementById('genelSkor').innerText, 35);
  assert.equal(ctx.document.getElementById('riskSummary').innerText, 'Özet hazırlanamadı.');
  assert.equal(ctx.document.getElementById('decisionBadge').style.color, 'var(--danger)');
  assert.match(ctx.document.getElementById('gucluYonler').innerHTML, /Veri yok/);
  assert.match(ctx.document.getElementById('temelRiskler').innerHTML, /Risk saptanmadı/);
  assert.match(ctx.document.getElementById('oneriler').innerHTML, /Tavsiye yok/);
});

test('_renderReportData renders list items as text-safe content', () => {
  const ctx = setupApp(`
    <div id="genelSkor"></div>
    <div id="riskSummary"></div>
    <div id="kaliteSkor"></div>
    <div id="memnuniyetSkor"></div>
    <div id="yonetisimSkor"></div>
    <div id="decisionBadge"></div>
    <ul id="gucluYonler"></ul>
    <ul id="temelRiskler"></ul>
    <ul id="oneriler"></ul>
    <div id="sicilDetay"></div>
  `, { pathname: '/report.html' });

  ctx._renderReportData({
    genel_skor: 80,
    guclu_yonler: ['<script>alert(1)</script>'],
    kirmizi_bayraklar: ['<img src=x onerror=alert(1)>'],
    ne_yapmali: ['<b>kalın</b>'],
  });

  assert.doesNotMatch(ctx.document.getElementById('gucluYonler').innerHTML, /<script>/);
  assert.doesNotMatch(ctx.document.getElementById('temelRiskler').innerHTML, /<img /);
  assert.doesNotMatch(ctx.document.getElementById('oneriler').innerHTML, /<b>/);
});

test('startMarketAnalysis validates input, success path, and API failure', async () => {
  const ctx = setupApp(`
    <input id="marketCompanyName" value="" />
    <input id="marketCompanyAddress" value="" />
    <div id="marketLoading" style="display:none"></div>
  `, { pathname: '/market.html' });

  const overlay = ctx.document.getElementById('marketLoading');

  await ctx.startMarketAnalysis();
  assert.equal(overlay.style.display, 'none');

  ctx.document.getElementById('marketCompanyName').value = 'Nova';
  ctx.document.getElementById('marketCompanyAddress').value = 'Ankara';
  ctx.fetch = async () => createFetchResponse({ ok: true, jsonData: { a: 1 } });

  await ctx.startMarketAnalysis();
  assert.equal(overlay.style.display, 'flex');
  assert.equal(ctx.localStorage.getItem('marketData'), '{"a":1}');
  assert.match(ctx.window.location.href, /report\.html\?type=market&name=Nova/);

  let alertMessage = '';
  ctx.alert = (msg) => {
    alertMessage = msg;
  };
  ctx.window.alert = ctx.alert;
  ctx.fetch = async () => createFetchResponse({ ok: false, jsonData: {} });
  await ctx.startMarketAnalysis();
  assert.match(alertMessage, /Hata: API hatası/);
  assert.equal(overlay.style.display, 'none');
});
