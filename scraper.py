"""
scraper.py — SafeTrade AI Data Mining Microservice
---------------------------------------------------
Responsible for:
  - Defining the canonical Pydantic output schema.
  - Fetching recent news headlines (via requests + BeautifulSoup).
    Primary source  : Google News RSS feed (key-free).
    Secondary source: Bing News HTML scrape (BeautifulSoup, browser-spoofed).
    Fallback        : generate_mock_complaint_data() synthetic data.
  - Fetching financial metrics and market data (via yfinance).
  - Gathering consumer/regulatory complaint data.
  - generate_mock_complaint_data(): Turkish MVP demo fallback generator.
"""

from __future__ import annotations

import logging
import random
import urllib.parse
from datetime import date, timedelta
from typing import Any

import requests
import yfinance as yf
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared HTTP session with browser-like headers to reduce scraping blocks
# ---------------------------------------------------------------------------
_SESSION = requests.Session()
_SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9,tr;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
)


# ---------------------------------------------------------------------------
# Pydantic Schema
# ---------------------------------------------------------------------------

class NewsItem(BaseModel):
    """A single news headline related to the company."""
    title: str = Field(..., description="Headline text of the news article.")
    url: str | None = Field(None, description="URL of the source article, if available.")
    published_at: str | None = Field(None, description="Publication timestamp (ISO-8601 or free-form string).")
    source: str | None = Field(None, description="Name of the publishing outlet.")


class Complaint(BaseModel):
    """A single consumer or regulatory complaint record."""
    title: str = Field(..., description="Brief title or subject of the complaint.")
    date: str | None = Field(None, description="Date the complaint was filed (YYYY-MM-DD).")
    body: str | None = Field(None, description="Summary or full body of the complaint text.")
    source: str | None = Field(None, description="Platform or database the complaint originated from.")


class FinancialMetrics(BaseModel):
    """Key fundamental/financial metrics for the company."""
    market_cap: float | None = Field(None, description="Market capitalisation in USD.")
    pe_ratio: float | None = Field(None, description="Trailing price-to-earnings ratio.")
    eps: float | None = Field(None, description="Trailing twelve-month earnings per share.")
    revenue: float | None = Field(None, description="Annual revenue in USD.")
    net_income: float | None = Field(None, description="Annual net income in USD.")
    debt_to_equity: float | None = Field(None, description="Total debt-to-equity ratio.")
    return_on_equity: float | None = Field(None, description="Return on equity (decimal, e.g. 0.15 = 15%).")

    model_config = {"extra": "allow"}  # Allow additional fields from the data source


class MarketData(BaseModel):
    """Real-time / recent market trading data for the company's stock."""
    ticker: str = Field(..., description="Stock ticker symbol (e.g. AAPL).")
    current_price: float | None = Field(None, description="Latest closing/current price in USD.")
    previous_close: float | None = Field(None, description="Previous trading session closing price.")
    day_high: float | None = Field(None, description="Intraday high price.")
    day_low: float | None = Field(None, description="Intraday low price.")
    volume: int | None = Field(None, description="Trading volume for the current / most recent session.")
    fifty_two_week_high: float | None = Field(None, description="52-week high price.")
    fifty_two_week_low: float | None = Field(None, description="52-week low price.")
    beta: float | None = Field(None, description="Stock beta (volatility vs. market).")

    model_config = {"extra": "allow"}


class CompanyReport(BaseModel):
    """
    Top-level output schema for the SafeTrade AI data mining microservice.
    This object is serialised to JSON and consumed by downstream services.
    """
    company_name: str = Field(..., description="Full legal name of the company being analysed.")
    generated_at: str = Field(
        default_factory=lambda: date.today().isoformat(),
        description="UTC date (YYYY-MM-DD) when this report was generated.",
    )
    recent_news: list[NewsItem] = Field(
        default_factory=list,
        description="List of recent news items mentioning the company.",
    )
    complaints: list[Complaint] = Field(
        default_factory=list,
        description="List of consumer or regulatory complaints filed against the company.",
    )
    financial_metrics: FinancialMetrics | None = Field(
        None,
        description="Fundamental financial metrics sourced from public filings / data providers.",
    )
    market_data: MarketData | None = Field(
        None,
        description="Real-time or end-of-day market trading data for the company's stock.",
    )


# ---------------------------------------------------------------------------
# Data-gathering helpers
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# News scraping — primary: Google News RSS  /  secondary: Bing News HTML
# ---------------------------------------------------------------------------

def _fetch_news_google_rss(query: str, max_results: int) -> list[NewsItem]:
    """
    Primary news source: Google News RSS feed.

    Parses the standard RSS <item> elements with BeautifulSoup's XML parser.
    Returns an empty list (does NOT raise) on any error so the caller can
    transparently fall through to the next source.
    """
    encoded = urllib.parse.quote_plus(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
    items: list[NewsItem] = []

    try:
        resp = _SESSION.get(url, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "xml")

        for tag in soup.find_all("item")[:max_results]:
            items.append(
                NewsItem(
                    title=tag.title.get_text(strip=True) if tag.title else "N/A",
                    url=tag.link.get_text(strip=True) if tag.link else None,
                    published_at=tag.pubDate.get_text(strip=True) if tag.pubDate else None,
                    source=tag.source.get_text(strip=True) if tag.source else None,
                )
            )
        logger.info("Google News RSS returned %d items for '%s'.", len(items), query)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Google News RSS failed for '%s': %s", query, exc)

    return items


def _fetch_news_bing_html(query: str, max_results: int) -> list[NewsItem]:
    """
    Secondary news source: Bing News HTML scrape via BeautifulSoup.

    Bing News renders headline cards as <div class="news-card"> elements.
    Each card contains:
      - <a class="title">  — headline text + href
      - <div class="source"> — publisher name
      - <span class="datetime"> — relative or absolute time string

    This is a best-effort scraper; Bing may change its DOM structure at any
    time.  Returns an empty list (does NOT raise) on any parsing failure.
    """
    encoded = urllib.parse.quote_plus(query)
    url = f"https://www.bing.com/news/search?q={encoded}&format=RSS"
    items: list[NewsItem] = []

    # Try the Bing RSS endpoint first (more stable than HTML)
    try:
        resp = _SESSION.get(url, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "xml")

        for tag in soup.find_all("item")[:max_results]:
            title_tag = tag.find("title")
            link_tag = tag.find("link")
            pub_tag = tag.find("pubDate")
            src_tag = tag.find("source")
            items.append(
                NewsItem(
                    title=title_tag.get_text(strip=True) if title_tag else "N/A",
                    url=link_tag.get_text(strip=True) if link_tag else None,
                    published_at=pub_tag.get_text(strip=True) if pub_tag else None,
                    source=src_tag.get_text(strip=True) if src_tag else None,
                )
            )
        logger.info("Bing News RSS returned %d items for '%s'.", len(items), query)
        return items
    except Exception as exc:  # noqa: BLE001
        logger.warning("Bing News RSS failed for '%s': %s — trying HTML scrape.", query, exc)

    # Fall back to scraping the HTML news page
    try:
        html_url = f"https://www.bing.com/news/search?q={encoded}"
        resp = _SESSION.get(html_url, timeout=12)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        cards = soup.select("div.news-card")[:max_results]
        for card in cards:
            title_tag = card.select_one("a.title")
            source_tag = card.select_one("div.source, span.source")
            time_tag = card.select_one("span.datetime, div.datetime")

            if not title_tag:
                continue
            items.append(
                NewsItem(
                    title=title_tag.get_text(strip=True),
                    url=title_tag.get("href"),
                    published_at=time_tag.get_text(strip=True) if time_tag else None,
                    source=source_tag.get_text(strip=True) if source_tag else None,
                )
            )
        logger.info("Bing News HTML scrape returned %d items for '%s'.", len(items), query)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Bing News HTML scrape failed for '%s': %s", query, exc)

    return items


def fetch_news(company_name: str, max_results: int = 10) -> list[NewsItem]:
    """
    Fetch recent news headlines for *company_name*.

    Strategy (waterfall):
      1. Google News RSS  — key-free, structured XML, most reliable.
      2. Bing News RSS / HTML scrape — fallback if Google is blocked.
      3. Mock data from generate_mock_complaint_data() — last-resort demo fallback.

    Returns up to *max_results* NewsItem objects.
    """
    # --- Source 1: Google News RSS ---
    items = _fetch_news_google_rss(company_name, max_results)
    if items:
        return items

    # --- Source 2: Bing News ---
    logger.info("Falling back to Bing News for '%s'.", company_name)
    items = _fetch_news_bing_html(company_name, max_results)
    if items:
        return items

    # --- Source 3: Mock data ---
    logger.warning(
        "All live news sources failed for '%s'. Using mock data for demo.",
        company_name,
    )
    mock = generate_mock_complaint_data(company_name)
    return mock["news"]


def fetch_financial_data(ticker_symbol: str) -> tuple[FinancialMetrics | None, MarketData | None]:
    """
    Fetch financial metrics and market data for *ticker_symbol* using yfinance.

    Returns a tuple of (FinancialMetrics, MarketData). Either element may be
    None if the ticker is invalid or the fetch fails.
    """
    try:
        ticker = yf.Ticker(ticker_symbol)
        info: dict[str, Any] = ticker.info

        financial_metrics = FinancialMetrics(
            market_cap=info.get("marketCap"),
            pe_ratio=info.get("trailingPE"),
            eps=info.get("trailingEps"),
            revenue=info.get("totalRevenue"),
            net_income=info.get("netIncomeToCommon"),
            debt_to_equity=info.get("debtToEquity"),
            return_on_equity=info.get("returnOnEquity"),
        )

        market_data = MarketData(
            ticker=ticker_symbol.upper(),
            current_price=info.get("currentPrice"),
            previous_close=info.get("previousClose"),
            day_high=info.get("dayHigh"),
            day_low=info.get("dayLow"),
            volume=info.get("volume"),
            fifty_two_week_high=info.get("fiftyTwoWeekHigh"),
            fifty_two_week_low=info.get("fiftyTwoWeekLow"),
            beta=info.get("beta"),
        )

        return financial_metrics, market_data

    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to fetch financial data for ticker '%s': %s", ticker_symbol, exc)
        return None, None


def fetch_complaints(company_name: str) -> list[Complaint]:
    """
    Fetch consumer complaints for *company_name*.

    Currently falls back to generate_mock_complaint_data() (Turkish MVP demo data).
    In production, replace with live integrations such as:
      - CFPB Consumer Complaint Database (https://www.consumerfinance.gov/data-research/consumer-complaints/)
      - Better Business Bureau API
      - SEC complaint filings
      - Şikayetvar / Sikayetvar Turkish complaint board scrape
    """
    logger.info(
        "No live complaint source configured for '%s'. Returning mock data.",
        company_name,
    )
    mock = generate_mock_complaint_data(company_name)
    return mock["complaints"]


# ---------------------------------------------------------------------------
# MVP Demo Fallback — Turkish synthetic data generator
# ---------------------------------------------------------------------------

def generate_mock_complaint_data(company_name: str) -> dict[str, list]:
    """
    Generate realistic-looking **Turkish** fake complaints and news headlines
    for MVP demo / offline fallback purposes.

    Returns a dict with two keys:
      ``complaints`` — list[Complaint]  (3–5 items)
      ``news``       — list[NewsItem]   (3–5 items)

    All dates are randomised within the past 90 days so the data looks fresh
    on every demo run.

    Example usage::

        mock = generate_mock_complaint_data("Garanti BBVA")
        print(mock["complaints"][0].title)
        # → "Garanti BBVA ödememizi 60 gündür yapmıyor!"
    """

    def _random_date(days_back: int = 90) -> str:
        """Return a random YYYY-MM-DD string within the last *days_back* days."""
        offset = random.randint(1, days_back)
        return (date.today() - timedelta(days=offset)).isoformat()

    # ------------------------------------------------------------------
    # Complaint templates  (Turkish)
    # Placeholders: {company} is substituted with company_name.
    # ------------------------------------------------------------------
    COMPLAINT_TEMPLATES: list[dict[str, str]] = [
        {
            "title": "{company} ödememizi 60 gündür yapmıyor!",
            "body": (
                "{company} ile yaptığımız sözleşme kapsamında hak ettiğimiz "
                "60.000 TL'lik ödeme 60 gündür yapılmadı. Müşteri hizmetleri "
                "her aramada 'sistemi kontrol ediyoruz' deyip kapatıyor. "
                "Bu durumun bir an önce çözülmesini talep ediyoruz."
            ),
            "source": "Şikayetvar",
        },
        {
            "title": "{company} hesabımı haksız yere kapattı",
            "body": (
                "Herhangi bir uyarı veya bildirim yapılmaksızın {company} "
                "tarafından hesabım tek taraflı olarak kapatıldı. "
                "İçerideki bakiyeme erişemiyorum ve müşteri temsilcileri "
                "neden kapatıldığını açıklamayı reddediyor."
            ),
            "source": "Şikayetvar",
        },
        {
            "title": "{company} yanlış faiz uyguluyor – mağduruz",
            "body": (
                "{company} kredi sözleşmemizde belirlenen faiz oranını "
                "tek taraflı olarak değiştirdi. Sözleşmede %2,5 olan aylık "
                "faiz oranı %4,1'e yükseltildi. Tüketici haklarımızın "
                "çiğnenmesine izin vermeyeceğiz."
            ),
            "source": "Sikayetvar",
        },
        {
            "title": "{company} para transferim 3 haftadır askıda",
            "body": (
                "3 hafta önce yaptığım 25.000 TL'lik EFT transferi hâlâ "
                "alıcıya ulaşmadı. {company} destek hattı sorunu çözmek "
                "bir yana, havaleyi sisteminizde göremiyoruz diyor. "
                "BDDK'ya şikâyet etmek zorunda kalacağım."
            ),
            "source": "Şikayetvar",
        },
        {
            "title": "{company} müşteri hizmetleri ulaşılamaz durumda",
            "body": (
                "Son 2 haftadır {company} müşteri hizmetlerine ulaşmak "
                "imkânsız hale geldi. Çağrı merkezi ortalama 45 dakika "
                "bekletip düşürüyor; mobil uygulama ise sürekli hata "
                "veriyor. Bu hizmet kalitesi kabul edilemez."
            ),
            "source": "Google Reviews",
        },
        {
            "title": "{company} komisyon ücretlerini gizlice artırdı",
            "body": (
                "{company} Ocak ayından itibaren işlem komisyonlarını "
                "müşterilere haber vermeden %40 oranında artırdı. "
                "Bu değişikliği hesap özetimde fark ettim; hiçbir "
                "bildirim veya onay e-postası almadım."
            ),
            "source": "Şikayetvar",
        },
    ]

    # ------------------------------------------------------------------
    # News headline templates  (Turkish + English mix, as seen in real feeds)
    # ------------------------------------------------------------------
    NEWS_TEMPLATES: list[dict[str, str]] = [
        {
            "title": "{company} hakkında BDDK soruşturması başlatıldı",
            "source": "Dünya Gazetesi",
            "url": "https://www.dunya.com/finans/haberler",
        },
        {
            "title": "{company} 2024 yılı kâr rakamlarını açıkladı",
            "source": "Bloomberg HT",
            "url": "https://www.bloomberght.com/haberler",
        },
        {
            "title": "{company} yeni dijital bankacılık platformunu duyurdu",
            "source": "Ekonomi Haberleri",
            "url": "https://www.ekonomi.com/haberler",
        },
        {
            "title": "{company} müşteri şikâyetleri rekor seviyeye ulaştı",
            "source": "Hürriyet Ekonomi",
            "url": "https://www.hurriyet.com.tr/ekonomi",
        },
        {
            "title": "{company} CEO'su görevinden istifa etti",
            "source": "Milliyet",
            "url": "https://www.milliyet.com.tr/ekonomi",
        },
        {
            "title": "{company} raises $50M in Series B to expand across MENA",
            "source": "TechCrunch",
            "url": "https://techcrunch.com",
        },
        {
            "title": "{company} partners with local banks to offer BNPL services",
            "source": "FinTech Futures",
            "url": "https://www.fintechfutures.com",
        },
    ]

    # ------------------------------------------------------------------
    # Sample and build the mock data
    # ------------------------------------------------------------------
    num_complaints = random.randint(3, 5)
    num_news = random.randint(3, 5)

    sampled_complaints = random.sample(COMPLAINT_TEMPLATES, k=min(num_complaints, len(COMPLAINT_TEMPLATES)))
    sampled_news = random.sample(NEWS_TEMPLATES, k=min(num_news, len(NEWS_TEMPLATES)))

    complaints = [
        Complaint(
            title=tpl["title"].format(company=company_name),
            date=_random_date(),
            body=tpl["body"].format(company=company_name),
            source=tpl["source"],
        )
        for tpl in sampled_complaints
    ]

    news = [
        NewsItem(
            title=tpl["title"].format(company=company_name),
            url=tpl.get("url"),
            published_at=_random_date(30),
            source=tpl.get("source"),
        )
        for tpl in sampled_news
    ]

    logger.info(
        "Generated %d mock complaints and %d mock news items for '%s'.",
        len(complaints),
        len(news),
        company_name,
    )
    return {"complaints": complaints, "news": news}
