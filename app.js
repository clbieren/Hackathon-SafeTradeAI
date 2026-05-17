/**
 * SafeTrade AI - Frontend Logic (Multi-Page Version)
 * Backend: Eren API (FastAPI)
 */

const API_BASE = "https://safetradeai-production.up.railway.app";
let provincesData = [];

function _escapeHtml(value) {
    return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
}

function _normalizeText(value, fallback = '') {
    const text = String(value ?? '').trim();
    return text || fallback;
}

function _setSafeList(container, values, bulletColor, fallbackText) {
    if (!container) return;
    const sourceValues = Array.isArray(values) ? values : [];
    const normalized = sourceValues
        .map((entry) => _normalizeText(entry))
        .filter(Boolean);
    const finalValues = normalized.length > 0 ? normalized : [fallbackText];

    container.innerHTML = '';
    finalValues.forEach((value) => {
        const li = document.createElement('li');
        const bullet = document.createElement('span');
        bullet.className = 'bullet';
        bullet.style.background = bulletColor;
        li.appendChild(bullet);
        li.appendChild(document.createTextNode(` ${value}`));
        container.appendChild(li);
    });
}

// ─── FIX 1: Daktilo animasyonu ───────────────────────────────────────────────
function _typewriterAppend(element, text, speed = 18) {
    if (!element || !text) return Promise.resolve();
    return new Promise((resolve) => {
        let i = 0;
        const interval = setInterval(() => {
            element.textContent += text[i];
            element.scrollTop = element.scrollHeight;
            i++;
            if (i >= text.length) {
                clearInterval(interval);
                resolve();
            }
        }, speed);
    });
}

// ─── FIX 2: SVG Score Circle (puana göre arc) ────────────────────────────────
function _renderScoreCircle(score) {
    const numScore = Number(score) || 0;

    let color = '#ef4444';
    if (numScore >= 75) color = '#10b981';
    else if (numScore >= 50) color = '#f59e0b';

    const radius = 80;
    const circumference = 2 * Math.PI * radius;
    const offset = circumference - (numScore / 100) * circumference;

    const container = document.getElementById('scoreCircleContainer');
    if (!container) return;

    container.innerHTML = `
        <svg width="200" height="200" viewBox="0 0 200 200" style="transform:rotate(-90deg)">
            <circle
                cx="100" cy="100" r="${radius}"
                fill="none"
                stroke="rgba(255,255,255,0.05)"
                stroke-width="12"
            />
            <circle
                cx="100" cy="100" r="${radius}"
                fill="none"
                stroke="${color}"
                stroke-width="12"
                stroke-linecap="round"
                stroke-dasharray="${circumference}"
                stroke-dashoffset="${circumference}"
                style="transition: stroke-dashoffset 1.2s cubic-bezier(0.4,0,0.2,1);"
                id="scoreArc"
            />
        </svg>
        <div style="position:absolute; display:flex; flex-direction:column; align-items:center; justify-content:center; inset:0;">
            <div class="score-num" id="genelSkor" style="color:${color}">${numScore}</div>
            <div class="score-total">/ 100</div>
        </div>
    `;

    requestAnimationFrame(() => {
        requestAnimationFrame(() => {
            const arc = document.getElementById('scoreArc');
            if (arc) arc.style.strokeDashoffset = offset;
        });
    });
}

document.addEventListener('DOMContentLoaded', () => {
    const path = window.location.pathname;
    if (path.includes('discovery.html')) {
        loadProvinces();
    }
});

/**
 * 1. İl - İlçe Seçimi (Türkiye API)
 */
async function loadProvinces() {
    const citySelect = document.getElementById('citySelect');
    if (!citySelect) return;

    try {
        const response = await fetch('https://turkiyeapi.dev/api/v1/provinces');
        const data = await response.json();

        if (data.status === "OK") {
            provincesData = data.data;
            provincesData.sort((a, b) => a.name.localeCompare(b.name, 'tr'));

            citySelect.innerHTML = '<option value="">İl Seçiniz</option>';
            provincesData.forEach(prov => {
                const opt = document.createElement('option');
                opt.value = prov.name;
                opt.textContent = prov.name;
                citySelect.appendChild(opt);
            });

            citySelect.addEventListener('change', (e) => loadDistricts(e.target.value));
        }
    } catch (error) {
        console.error("Türkiye API hatası:", error);
    }
}

function loadDistricts(provinceName) {
    const districtSelect = document.getElementById('districtSelect');
    if (!districtSelect) return;

    if (!provinceName) {
        districtSelect.innerHTML = '<option value="">Önce İl Seçiniz</option>';
        districtSelect.disabled = true;
        return;
    }

    const province = provincesData.find(p => p.name === provinceName);
    if (province && province.districts) {
        districtSelect.disabled = false;
        districtSelect.innerHTML = '<option value="">Tüm İlçeler</option>';

        province.districts.sort((a, b) => a.name.localeCompare(b.name, 'tr'));
        province.districts.forEach(dist => {
            const opt = document.createElement('option');
            opt.value = dist.name;
            opt.textContent = dist.name;
            districtSelect.appendChild(opt);
        });
    }
}

/**
 * 2. Akıllı Keşif (Discovery & Auto-Seeding)
 */
async function fetchDiscoverResults() {
    const q = document.getElementById('qInput').value.trim();
    const city = document.getElementById('citySelect').value;
    const district = document.getElementById('districtSelect').value;
    const resultsDiv = document.getElementById('resultsList');
    const searchBtn = document.getElementById('searchBtn');

    resultsDiv.innerHTML = `
        <div class="loader-container">
            <div class="loader-ring"></div>
            <p style="margin-top:1rem; color:var(--text-dim); font-size:0.8rem; letter-spacing:1px">İSTİHBARAT TOPLANIYOR...</p>
        </div>
    `;
    searchBtn.disabled = true;

    try {
        let url = `${API_BASE}/discover?`;
        if (q) url += `q=${encodeURIComponent(q)}&`;
        if (city) url += `city=${encodeURIComponent(city)}&`;
        if (district) url += `district=${encodeURIComponent(district)}`;

        const response = await AuthManager.fetch(url);
        if (!response.ok) throw new Error("API hatası");
        const data = await response.json();

        resultsDiv.innerHTML = "";
        if (data.results.length === 0) {
            resultsDiv.innerHTML = '<div class="empty-state"><p>Sonuç bulunamadı.</p></div>';
        } else {
            data.results.forEach(company => {
                const report = company.report || {};
                const score = report.trust_score || 0;
                const scoreClass = score >= 50 ? 'high' : 'low';

                const card = document.createElement('div');
                card.className = 'company-card-new';
                card.innerHTML = `
                    <div class="company-header">
                        <div>
                            <div class="company-name">${_escapeHtml(_normalizeText(company.name, 'İsimsiz Şirket'))}</div>
                            <div class="company-id">${_escapeHtml(_normalizeText(company.tax_number, 'Vergi No Bekleniyor'))}</div>
                        </div>
                        <div class="score-pill ${scoreClass}">
                            <i data-lucide="shield"></i>
                            ${score.toFixed(0)}
                        </div>
                    </div>
                    <p style="font-size:0.8rem; color:var(--text-dim); margin-bottom:1rem;">${_escapeHtml(_normalizeText(company.address, 'Adres bilgisi mevcut değil.'))}</p>
                    <button class="btn-full" onclick="window.location.href='report.html?id=${encodeURIComponent(String(company.id || ''))}&name=${encodeURIComponent(_normalizeText(company.name, ''))}'">
                        Analizi Görüntüle
                        <i data-lucide="chevron-right"></i>
                    </button>
                `;
                resultsDiv.appendChild(card);
            });
            lucide.createIcons();
        }
    } catch (error) {
        resultsDiv.innerHTML = `<div class="empty-state"><p>Hata: ${_escapeHtml(_normalizeText(error?.message, 'Beklenmeyen hata'))}</p></div>`;
    } finally {
        searchBtn.disabled = false;
    }
}

/**
 * 3. Şirket Derin Analizi (SSE Streaming)
 */
async function startDeepAnalysis(companyId, fullAddress) {
    const reportContent = document.getElementById('reportContent');
    const reportLoading = document.getElementById('reportLoading');
    const streamView = document.getElementById('streamView');
    const statusBadge = document.getElementById('reportStatus');
    const nameHeader = document.getElementById('reportCompanyName');
    const metaArea = document.getElementById('reportMeta');

    const urlParams = new URLSearchParams(window.location.search);
    const companyName = urlParams.get('name') || 'Firma';

    nameHeader.innerText = companyName;
    metaArea.innerText = `ID: ${companyId} | SİSTEM DURUMU: AKTİF`;

    if (streamView) streamView.textContent = '';

    const _updateStatus = async (message) => {
        if (!statusBadge) return;
        statusBadge.innerText = '';
        await _typewriterAppend(statusBadge, message.toUpperCase(), 25);
    };

    const _appendToStream = async (text) => {
        if (!streamView) return;
        await _typewriterAppend(streamView, text + '\n', 12);
    };

    try {
        const addressParam = fullAddress ? `?full_address=${encodeURIComponent(fullAddress)}` : '';
        const response = await AuthManager.fetch(`${API_BASE}/generate-report/${companyId}${addressParam}`, { method: 'POST' });

        if (!response.ok || !response.body) {
            throw new Error('Rapor akışı başlatılamadı');
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let sseBuffer = '';

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            sseBuffer += decoder.decode(value, { stream: true });
            const lines = sseBuffer.split('\n');
            sseBuffer = lines.pop();

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                const dataRaw = line.slice(6).trim();
                if (dataRaw === '[DONE]') break;

                try {
                    const payload = JSON.parse(dataRaw);

                    if (payload.type === 'status') {
                        await _updateStatus(payload.message);
                        await _appendToStream(`> ${payload.message}`);

                    } else if (payload.type === 'data_sources') {
                        const sources = payload.sources || {};
                        for (const [k, v] of Object.entries(sources)) {
                            await _appendToStream(`  [${v === 'OK' ? '✓' : '✗'}] ${k}: ${v}`);
                        }

                    } else if (payload.type === 'chunk') {
                        if (streamView) {
                            streamView.textContent += payload.text;
                            streamView.scrollTop = streamView.scrollHeight;
                        }

                    } else if (payload.type === 'result') {
                        _renderReportData(payload.data);
                        reportLoading.style.display = 'none';
                        reportContent.style.display = 'block';
                        lucide.createIcons();
                    }
                } catch (e) {
                    console.warn('SSE parse hatası:', e);
                }
            }
        }
    } catch (error) {
        console.error("Analysis error:", error);
        if (statusBadge) statusBadge.innerText = 'HATA';
        if (reportLoading) reportLoading.style.display = 'none';
    }
}

function _renderReportData(data) {
    const setText = (id, value) => {
        const el = document.getElementById(id);
        if (el) el.innerText = value ?? '--';
    };

    _renderScoreCircle(data.genel_skor);
    
    setText('kaliteSkor', data.kalite_skoru ?? '--');
    setText('memnuniyetSkor', data.musteri_memnuniyeti_skoru ?? '--');
    setText('yonetisimSkor', data.operasyon_ve_yonetisim_skoru ?? data.operasyon_ve_yonetim_skoru ?? '--');
    setText('riskSummary', data.risk_summary);
    setText('decisionBadge', data.tedarikci_karari);
    
    const sicil = data.resmi_sicil_detaylari;
    setText('sicilDetay', (typeof sicil === 'string' && sicil.trim()) ? sicil : 'Resmi sicil verisi bulunamadı.');

    const guclu = document.getElementById('gucluYonler');
    const riskler = document.getElementById('temelRiskler');
    const oneriler = document.getElementById('oneriler');

    const gucluList = Array.isArray(data.guclu_yonler) && data.guclu_yonler.length > 0
        ? data.guclu_yonler
        : (Array.isArray(data.kirmizi_bayraklar) && data.kirmizi_bayraklar.length === 0
            ? ['Kritik risk tespit edilmedi']
            : []);

    if (guclu) _setSafeList(guclu, gucluList, 'var(--success)', 'Güçlü yön verisi bulunamadı');
    if (riskler) _setSafeList(riskler, data.kirmizi_bayraklar, 'var(--danger)', 'Risk saptanmadı');
    if (oneriler) _setSafeList(oneriler, data.ne_yapmali || [], 'var(--secondary)', 'Tavsiye yok');

    document.getElementById('reportLoading').style.display = 'none';
    document.getElementById('reportContent').style.display = 'block';
    lucide.createIcons();
}

/**
 * 4. Pazar Analizi
 */
async function startMarketAnalysis() {
    const compName = document.getElementById('marketCompanyName').value.trim();
    const compAddr = document.getElementById('marketCompanyAddress').value.trim();

    if (!compName || !compAddr) return;

    const overlay = document.getElementById('marketLoading');
    overlay.style.display = 'flex';

    try {
        const response = await AuthManager.fetch(`${API_BASE}/market-analysis`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ company_name: compName, full_address: compAddr })
        });

        if (!response.ok) throw new Error('API hatası');

        const data = await response.json();
        _renderMarketDataSPA(data, compName);

    } catch (error) {
        console.error('Market analiz hatası:', error);
    } finally {
        overlay.style.display = 'none';
    }
}

function _renderMarketDataSPA(data, name) {
    const formContainer = document.getElementById('marketFormContainer');
    const resultSection = document.getElementById('marketResult');
    if (formContainer) formContainer.style.display = 'none';
    if (resultSection) resultSection.style.display = 'block';

    // Skor
    const score = data.pazar_algisi_skoru ?? 0;
    const scoreEl = document.getElementById('resScore');
    if (scoreEl) scoreEl.textContent = score;

    // Skor rengi ve arc
    let color = '#ef4444';
    if (score >= 75) color = '#10b981';
    else if (score >= 50) color = '#f59e0b';

    const arc = document.getElementById('scoreArc');
    if (arc) {
        arc.style.stroke = color;
        const circumference = 2 * Math.PI * 50;
        const offset = circumference - (score / 100) * circumference;
        requestAnimationFrame(() => requestAnimationFrame(() => {
            arc.style.strokeDashoffset = offset;
        }));
    }
    if (scoreEl) scoreEl.style.color = color;

    // Metinler
    const setText = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.textContent = val ?? '';
    };
    setText('resCompanyName', name);
    setText('resSummary', data.stratejik_ozet || '');
    setText('resMeta', `SEKTÖREL ANALİZ | KAYNAK: ${String(data.data_source_type || 'MIXED').toUpperCase()}`);
    setText('resKiyaslama', data.birebir_kiyaslama || 'Rakip verisi bulunamadı.');

    // Listeler
    const setList = (id, arr, fallback) => {
        const el = document.getElementById(id);
        if (!el) return;
        const items = Array.isArray(arr) && arr.length > 0 ? arr : [fallback];
        el.innerHTML = items.map(i => `<li>${i}</li>`).join('');
    };
    setList('resGuclu', data.guclu_yonler, 'Veri yok');
    setList('resZayif', data.zayif_yonler, 'Zayıf yön bulunamadı');
    setList('resYapmali', data.ne_yapmali, 'Öneri bulunamadı');
    setList('resYapmamali', data.ne_yapmamali, 'Öneri bulunamadı');
    setList('resRakip', data.rakip_analizi, 'Rakip verisi yok');
    setList('resFinansal', data.finansal_tavsiyeler, 'Finansal tavsiye yok');

    // Context kaydet
    window._analysisContext = { ...data, company_name: name };

    lucide.createIcons();

    // Check alert status if available in UI context
    if (typeof checkAlertStatus === 'function') {
        checkAlertStatus(name);
    }
}