from flask import Flask, render_template, jsonify, request, redirect
import feedparser
import requests
from datetime import datetime, timedelta, timezone
from typing import List, Optional
import hashlib
import logging
from dataclasses import dataclass
from urllib.parse import urljoin
import time
import re
from bs4 import BeautifulSoup
from dateutil import parser

@dataclass
class Article:
    title: str
    content: str
    url: str
    published_date: datetime
    source: str
    thumbnail_url: Optional[str] = None
    country: Optional[str]    = None
    hash_id: str               = ""

    def __post_init__(self):
        # Catch any naive datetime here too
        if self.published_date.tzinfo is None:
            self.published_date = self.published_date.replace(tzinfo=timezone.utc)

        self.hash_id = hashlib.md5(f"{self.title}{self.url}".encode()).hexdigest()

class LGBTQNewsCollector:
    def __init__(self, newsapi_key: Optional[str] = None):
        self.newsapi_key = newsapi_key or "eb080d6f006a4d068a852f914673d458"
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'LGBTQ-News-Agent/1.0'})
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

        self.rss_feeds = {
            'advocate':        'https://www.advocate.com/rss.xml',
            'pinknews':        'https://www.pinknews.co.uk/feed/',
            'queerty':         'https://www.queerty.com/feed',
            'lgbtqnation':     'https://www.lgbtqnation.com/feed/',
            'washington_blade':'https://www.washingtonblade.com/feed/',
            'outsports':       'https://www.outsports.com/rss/index.xml',
            'them':            'https://www.them.us/feed/rss',
            'gaycitynews':     'https://gaycitynews.com/feed/',
        }

        self.lgbtq_keywords = [
            'LGBTQ', 'LGBT', 'gay', 'lesbian', 'transgender',
            'bisexual', 'queer', 'pride', 'rainbow', 'homosexual',
            'same-sex', 'gender identity', 'sexual orientation',
            'marriage equality', 'trans rights', 'gay rights',
            'GLAAD', 'Pride Month'
        ]

    def _parse_date(self, entry) -> Optional[datetime]:
        # Structured fields
        for fld in ('published_parsed', 'updated_parsed'):
            if hasattr(entry, fld) and getattr(entry, fld):
                ts = getattr(entry, fld)
                return datetime(*ts[:6], tzinfo=timezone.utc)
        # Fallback to textual
        for fld in ('published', 'updated'):
            if hasattr(entry, fld):
                try:
                    dt = parser.parse(getattr(entry, fld))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt
                except:
                    pass
        return None

    def _extract_content(self, entry) -> str:
        for fld in ('content', 'summary', 'description'):
            if hasattr(entry, fld):
                val = getattr(entry, fld)
                if isinstance(val, list) and val:
                    return val[0].get('value', '')
                if isinstance(val, str):
                    return val
        return ""

    def extract_thumbnail_from_rss(self, entry) -> Optional[str]:
        if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
            return entry.media_thumbnail[0].get('url')
        if hasattr(entry, 'media_content'):
            for m in entry.media_content:
                if m.get('type', '').startswith('image'):
                    return m.get('url')
        if hasattr(entry, 'enclosures'):
            for enc in entry.enclosures:
                if enc.get('type', '').startswith('image'):
                    return enc.get('href')
        # Inline <img>
        html = self._extract_content(entry)
        m = re.search(r'<img[^>]+src=[\'"]([^\'"]+)[\'"]', html)
        return m.group(1) if m else None

    def extract_thumbnail_from_url(self, url: str) -> Optional[str]:
        try:
            r = self.session.get(url, timeout=10)
            r.raise_for_status()
            soup = BeautifulSoup(r.content, 'html.parser')
            og = soup.find('meta', property='og:image')
            if og and og.get('content'):
                return og['content']
            tw = soup.find('meta', attrs={'name': 'twitter:image'})
            if tw and tw.get('content'):
                return tw['content']
            img = soup.find('img')
            if img and img.get('src'):
                return urljoin(url, img['src'])
        except Exception as e:
            self.logger.warning(f"Thumbnail failed for {url}: {e}")
        return None

    def collect_from_rss(self, hours_back: int = 24) -> List[Article]:
        articles = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
        for src, feed_url in self.rss_feeds.items():
            self.logger.info(f"Fetching RSS feed: {src}")
            feed = feedparser.parse(feed_url)
            if feed.bozo:
                self.logger.warning(f"{src} parse warning: {feed.bozo_exception}")
            for entry in feed.entries:
                pub = self._parse_date(entry) or datetime.now(timezone.utc)
                if pub < cutoff:
                    continue
                html = self._extract_content(entry)
                thumb = self.extract_thumbnail_from_rss(entry) \
                      or self.extract_thumbnail_from_url(entry.link)
                try:
                    articles.append(Article(
                        title          = entry.title,
                        content        = html,
                        url            = entry.link,
                        published_date = pub,
                        source         = src,
                        thumbnail_url  = thumb
                    ))
                except Exception as e:
                    self.logger.error(f"RSS→Article failed for {src}: {e}")
            time.sleep(1)
        return articles

    def collect_from_newsapi(self, hours_back: int = 24) -> List[Article]:
        if not self.newsapi_key:
            self.logger.warning("No NewsAPI key—skipping")
            return []
        articles = []
        from_date = (datetime.now(timezone.utc) - timedelta(hours=hours_back)) \
                    .strftime('%Y-%m-%d')
        for kw in self.lgbtq_keywords[:5]:
            try:
                params = {
                    'q'       : kw,
                    'from'    : from_date,
                    'sortBy'  : 'publishedAt',
                    'language': 'en',
                    'apiKey'  : self.newsapi_key,
                    'pageSize': 20
                }
                res = self.session.get(
                    "https://newsapi.org/v2/everything", params=params, timeout=10
                )
                res.raise_for_status()
                data = res.json()
                for art in data.get('articles', []):
                    if not art.get('content') or art['content'] == '[Removed]':
                        continue
                    dt = datetime.fromisoformat(
                        art['publishedAt'].replace('Z', '+00:00')
                    )
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    articles.append(Article(
                        title          = art['title'],
                        content        = art.get('description') or art['content'],
                        url            = art['url'],
                        published_date = dt,
                        source         = art['source']['name'],
                        thumbnail_url  = art.get('urlToImage')
                    ))
                time.sleep(2)
            except Exception as e:
                self.logger.error(f"NewsAPI '{kw}' failed: {e}")
        return articles

    def _deduplicate_articles(self, arts: List[Article]) -> List[Article]:
        seen, uniq = set(), []
        for a in arts:
            if a.hash_id not in seen:
                seen.add(a.hash_id)
                uniq.append(a)
        return uniq

    def collect_all_sources(self, hours_back: int = 24) -> List[Article]:
        rss_list = self.collect_from_rss(hours_back)
        api_list = self.collect_from_newsapi(hours_back)
        self.logger.info(f"RSS got {len(rss_list)}, NewsAPI got {len(api_list)}")
        combined = rss_list + api_list
        unique   = self._deduplicate_articles(combined)
        self.logger.info(f"{len(unique)} unique articles after dedupe")
        return unique

# ─── Flask App ─────────────────────────────────────────────────────

app = Flask(__name__)
collector = LGBTQNewsCollector()

@app.route('/')
def index():
    hours_back = request.args.get('hours', 24, type=int)
    articles   = collector.collect_all_sources(hours_back)

    # FINAL SAFETY-NET: normalize any stray naive datetimes
    for art in articles:
        if art.published_date.tzinfo is None:
            app.logger.warning(f"Normalizing naive date for '{art.title}'")
            art.published_date = art.published_date.replace(tzinfo=timezone.utc)

    articles.sort(key=lambda x: x.published_date, reverse=True)
    return render_template('news.html', articles=articles, hours_back=hours_back)

@app.route('/api/articles')
def api_articles():
    hours_back = request.args.get('hours', 24, type=int)
    arts       = collector.collect_all_sources(hours_back)

    for art in arts:
        if art.published_date.tzinfo is None:
            art.published_date = art.published_date.replace(tzinfo=timezone.utc)

    arts.sort(key=lambda x: x.published_date, reverse=True)
    return jsonify({
        'count'   : len(arts),
        'articles': [{
            'title'         : a.title,
            'content'       : a.content,
            'url'           : a.url,
            'published_date': a.published_date.isoformat(),
            'source'        : a.source,
            'thumbnail_url' : a.thumbnail_url,
            'hash_id'       : a.hash_id
        } for a in arts]
    })

@app.route('/refresh')
def refresh():
    return redirect('/')

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)