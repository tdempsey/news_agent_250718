from flask import Flask, render_template, jsonify, request, redirect
import feedparser
import requests
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional
import hashlib
import logging
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse
import time
import re
from bs4 import BeautifulSoup
import urllib.parse

@dataclass
class Article:
    """Data class for news articles with thumbnail support"""
    title: str
    content: str
    url: str
    published_date: datetime
    source: str
    thumbnail_url: Optional[str] = None
    country: Optional[str] = None
    hash_id: str = ""
    
    def __post_init__(self):
        content_hash = hashlib.md5(f"{self.title}{self.url}".encode()).hexdigest()
        self.hash_id = content_hash

class LGBTQNewsCollector:
    """Main news collection module for LGBTQ+ content with thumbnail extraction"""
    
    def __init__(self, newsapi_key: Optional[str] = None):
        self.newsapi_key = "eb080d6f006a4d068a852f914673d458"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'LGBTQ-News-Agent/1.0'
        })
        
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)
        
        # FIXED RSS feeds with proper Google News URLs
        self.rss_feeds = {
            'advocate': 'https://www.advocate.com/rss.xml',
            'pinknews': 'https://www.pinknews.co.uk/feed/',
            
            # Fixed Google News feeds 
            'google_lgbtq_atlanta': 'https://news.google.com/rss/search?q=gay%20atlanta%20-matt%20-jazz&hl=en-US&gl=US&ceid=US%3Aen',
            'google_lgbtq_general': 'https://news.google.com/rss/search?q=LGBTQ%20lesbian%20gay%20bisexual&hl=en-US&gl=US&ceid=US%3Aen',  # FIXED
            'google_gay_rights': 'https://news.google.com/rss/topics/CAAqIggKIhxDQkFTRHdvSkwyMHZNR1EyTTJ0MEVnSmxiaWdBUAE?hl=en-US&gl=US&ceid=US%3Aen',
            'google_pride_news': 'https://news.google.com/rss/search?q=pride%20month%20lgbtq&hl=en-US&gl=US&ceid=US%3Aen',
            'google_transgender_news': 'https://news.google.com/rss/search?q=transgender%20rights&hl=en-US&gl=US&ceid=US%3Aen',
            
            'theguardian': 'https://www.theguardian.com/world/lgbt-rights/rss',
            'queerty': 'https://www.queerty.com/feed',
            'lgbtqnation': 'https://www.lgbtqnation.com/feed/',
            'washington_blade': 'https://www.washingtonblade.com/feed/',
            'outsports': 'https://www.outsports.com/rss/index.xml',
            'them': 'https://www.them.us/feed/rss',
            'gaycitynews': 'https://gaycitynews.com/feed/',
            'soundcloud': 'http://feeds.soundcloud.com/users/soundcloud:users:2640728/sounds.rss',
            'getoutspoken': 'https://getoutspoken.com/',
        }
        
        self.lgbtq_keywords = [
            'LGBTQ', 'LGBT', 'gay', 'lesbian', 'transgender', 'bisexual', 
            'queer', 'pride', 'rainbow', 'homosexual', 'same-sex', 
            'gender identity', 'sexual orientation', 'marriage equality',
            'trans rights', 'gay rights', 'GLAAD', 'Pride Month'
        ]
        
        # Default excluded keywords (can be overridden)
        self.default_excluded_keywords = [
            'death', 'died', 'suicide', 'murder', 'killed', 'violence',
            'attack', 'assault', 'harassment', 'abuse', 'hate crime'
        ]

    def normalize_datetime(self, dt: datetime) -> datetime:
        """Normalize datetime to timezone-aware UTC"""
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _fix_google_news_url(self, url: str) -> str:
        """Convert Google News web URLs to proper RSS format"""
        if 'news.google.com' not in url:
            return url
        
        # Fix search URLs
        if '/search?' in url and '/rss/' not in url:
            return url.replace('/search?', '/rss/search?')
        
        # Fix topic URLs  
        if '/topics/' in url and '/rss/' not in url:
            return url.replace('/topics/', '/rss/topics/')
        
        return url

    def _handle_google_news_feed(self, feed_url: str, source_name: str):
        """Special handling for Google News feeds with fallbacks"""
        try:
            # Fix the URL format first
            fixed_url = self._fix_google_news_url(feed_url)
            
            if fixed_url != feed_url:
                self.logger.info(f"Fixed Google News URL for {source_name}: {fixed_url}")
            
            # Try to fetch with specific headers that Google News likes
            headers = {
                'User-Agent': 'Mozilla/5.0 (compatible; NewsBot/1.0; +http://www.example.com/bot)',
                'Accept': 'application/rss+xml, application/xml, text/xml'
            }
            
            # Use requests to fetch with custom headers
            response = self.session.get(fixed_url, headers=headers, timeout=15)
            response.raise_for_status()
            
            # Parse the response
            feed = feedparser.parse(response.content)
            
            # Check if we got valid content
            if not feed.entries and hasattr(feed, 'bozo') and feed.bozo:
                self.logger.warning(f"Google News feed {source_name} returned no entries, trying alternative approach...")
                
                # Try the original URL as fallback
                fallback_feed = feedparser.parse(feed_url)
                if fallback_feed.entries:
                    return fallback_feed
                
                # If still no luck, skip this feed for this round
                self.logger.warning(f"Skipping {source_name} due to parsing issues")
                return feedparser.FeedParserDict()  # Return empty feed
            
            return feed
            
        except Exception as e:
            self.logger.error(f"Error handling Google News feed {source_name}: {e}")
            return feedparser.FeedParserDict()  # Return empty feed

    def _fetch_and_fix_feed(self, feed_url: str, source_name: str):
        """Enhanced feed fetcher with special handling for different sources"""
        try:
            # Special handling for Google News feeds
            if 'news.google.com' in feed_url:
                return self._handle_google_news_feed(feed_url, source_name)
            
            # Special handling for The Advocate feed (encoding issues)
            elif 'advocate.com' in feed_url:
                response = self.session.get(feed_url, timeout=15)
                response.raise_for_status()
                
                content = response.text
                content = content.replace('encoding="us-ascii"', 'encoding="utf-8"')
                content = content.replace("encoding='us-ascii'", "encoding='utf-8'")
                
                return feedparser.parse(content)
            
            # Standard handling for other feeds
            else:
                return feedparser.parse(feed_url)
                
        except Exception as e:
            self.logger.error(f"Error fetching feed {source_name}: {e}")
            return feedparser.FeedParserDict()  # Return empty feed

    def validate_feed_health(self) -> Dict[str, bool]:
        """Check which feeds are currently working"""
        feed_health = {}
        
        for source_name, feed_url in self.rss_feeds.items():
            try:
                self.logger.info(f"Testing feed: {source_name}")
                
                # Quick test fetch
                feed = self._fetch_and_fix_feed(feed_url, source_name)
                
                # Check if feed has entries and no major errors
                has_entries = bool(feed.entries)
                has_major_error = hasattr(feed, 'bozo') and feed.bozo and 'syntax error' in str(feed.bozo_exception)
                
                feed_health[source_name] = has_entries and not has_major_error
                
                if not feed_health[source_name]:
                    self.logger.warning(f"Feed {source_name} appears unhealthy: entries={has_entries}, error={has_major_error}")
                
            except Exception as e:
                self.logger.error(f"Feed {source_name} failed health check: {e}")
                feed_health[source_name] = False
        
        healthy_feeds = sum(feed_health.values())
        total_feeds = len(feed_health)
        self.logger.info(f"Feed health check complete: {healthy_feeds}/{total_feeds} feeds healthy")
        
        return feed_health

    def filter_articles_by_keywords(self, articles: List[Article], exclude_keywords: List[str] = None) -> List[Article]:
        """Filter out articles containing excluded keywords"""
        if not exclude_keywords:
            exclude_keywords = self.default_excluded_keywords
            
        if not exclude_keywords:
            return articles
        
        filtered_articles = []
        excluded_count = 0
        
        # Convert keywords to lowercase for case-insensitive matching
        exclude_keywords_lower = [kw.lower() for kw in exclude_keywords]
        
        for article in articles:
            # Check title and content for excluded keywords
            text_to_check = f"{article.title} {article.content}".lower()
            
            # Check if any excluded keyword appears in the article
            contains_excluded = any(keyword in text_to_check for keyword in exclude_keywords_lower)
            
            if not contains_excluded:
                filtered_articles.append(article)
            else:
                excluded_count += 1
                self.logger.debug(f"Excluded article: {article.title[:50]}...")
        
        if excluded_count > 0:
            self.logger.info(f"Filtered out {excluded_count} articles containing excluded keywords")
        
        return filtered_articles

    def extract_thumbnail_from_rss(self, entry) -> Optional[str]:
        """Extract thumbnail image from RSS entry"""
        # Check for media:thumbnail or media:content
        if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
            return entry.media_thumbnail[0].get('url')
        
        if hasattr(entry, 'media_content') and entry.media_content:
            for media in entry.media_content:
                if media.get('type', '').startswith('image'):
                    return media.get('url')
        
        # Check for enclosure
        if hasattr(entry, 'enclosures') and entry.enclosures:
            for enclosure in entry.enclosures:
                if enclosure.get('type', '').startswith('image'):
                    return enclosure.get('href')
        
        # Parse RAW content for images (before cleaning)
        raw_content = self._get_raw_content(entry)
        if raw_content:
            # Try multiple image extraction patterns
            patterns = [
                r'<img[^>]+src=[\'"]([^\'"]+)[\'"][^>]*>',
                r'<figure[^>]*>.*?<img[^>]+src=[\'"]([^\'"]+)[\'"].*?</figure>',
                r'background-image:\s*url\([\'"]?([^\'"]+)[\'"]?\)',
                r'data-src=[\'"]([^\'"]+)[\'"]',
                r'srcset=[\'"]([^\'"]+)[\'"]'
            ]
            
            for pattern in patterns:
                img_match = re.search(pattern, raw_content, re.DOTALL | re.IGNORECASE)
                if img_match:
                    url = img_match.group(1)
                    # Skip data URLs and very small images
                    if not url.startswith('data:') and 'pixel' not in url.lower():
                        return url
        
        return None

    def _get_raw_content(self, entry) -> str:
        """Get raw HTML content without cleaning"""
        content_fields = ['content', 'summary', 'description']
        
        for field in content_fields:
            if hasattr(entry, field):
                content = getattr(entry, field)
                if isinstance(content, list) and content:
                    return content[0].get('value', '')
                elif isinstance(content, str):
                    return content
        
        return ""

    def extract_thumbnail_from_url(self, url: str) -> Optional[str]:
        """Extract thumbnail from article URL using Open Graph tags"""
        try:
            response = self.session.get(url, timeout=10)
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Try multiple meta tag approaches
                meta_selectors = [
                    ('meta', {'property': 'og:image'}),
                    ('meta', {'property': 'og:image:url'}),
                    ('meta', {'name': 'twitter:image'}),
                    ('meta', {'name': 'twitter:image:src'}),
                    ('meta', {'property': 'twitter:image'}),
                    ('meta', {'name': 'msapplication-TileImage'}),
                    ('meta', {'itemprop': 'image'}),
                ]
                
                for tag_name, attrs in meta_selectors:
                    meta_tag = soup.find(tag_name, attrs)
                    if meta_tag and meta_tag.get('content'):
                        img_url = meta_tag['content']
                        if img_url and not img_url.startswith('data:'):
                            return urljoin(url, img_url)
                
                # Try structured data
                json_lds = soup.find_all('script', type='application/ld+json')
                for script in json_lds:
                    try:
                        import json
                        data = json.loads(script.string)
                        if isinstance(data, dict) and 'image' in data:
                            img = data['image']
                            if isinstance(img, list) and img:
                                return urljoin(url, img[0])
                            elif isinstance(img, str):
                                return urljoin(url, img)
                    except:
                        continue
                
                # Try article content images
                article_selectors = [
                    'article img',
                    '.entry-content img',
                    '.post-content img', 
                    '.article-body img',
                    'main img'
                ]
                
                for selector in article_selectors:
                    img_tag = soup.select_one(selector)
                    if img_tag and img_tag.get('src'):
                        src = img_tag['src']
                        if not src.startswith('data:') and 'pixel' not in src.lower():
                            return urljoin(url, src)
                    
        except Exception as e:
            self.logger.warning(f"Failed to extract thumbnail from {url}: {e}")
        
        return None

    def collect_from_rss_with_resilience(self, hours_back: int = 24) -> List[Article]:
        """Collect articles from RSS feeds with improved error handling"""
        articles = []
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours_back)
        failed_feeds = []
        successful_feeds = []
        
        for source_name, feed_url in self.rss_feeds.items():
            try:
                self.logger.info(f"Fetching RSS feed: {source_name}")
                
                # Use enhanced feed fetcher
                feed = self._fetch_and_fix_feed(feed_url, source_name)
                
                if not feed.entries:
                    failed_feeds.append(source_name)
                    self.logger.warning(f"No entries found for {source_name}")
                    continue
                
                entry_count = 0
                for entry in feed.entries:
                    try:
                        pub_date = self._parse_date(entry)
                        
                        if pub_date:
                            normalized_pub_date = self.normalize_datetime(pub_date)
                            if normalized_pub_date < cutoff_time:
                                continue
                        
                        content = self._extract_content(entry)
                        thumbnail_url = self.extract_thumbnail_from_rss(entry)
                        
                        if not thumbnail_url:
                            thumbnail_url = self.extract_thumbnail_from_url(entry.link)
                        
                        final_pub_date = normalized_pub_date if pub_date else datetime.now(timezone.utc)
                        
                        article = Article(
                            title=entry.title,
                            content=content,
                            url=entry.link,
                            published_date=final_pub_date,
                            source=source_name,
                            thumbnail_url=thumbnail_url
                        )
                        
                        articles.append(article)
                        entry_count += 1
                        
                    except Exception as e:
                        self.logger.error(f"Error processing entry from {source_name}: {e}")
                        continue
                
                if entry_count > 0:
                    successful_feeds.append(f"{source_name} ({entry_count} articles)")
                    self.logger.info(f"Successfully collected {entry_count} articles from {source_name}")
                
                time.sleep(1)  # Rate limiting
                
            except Exception as e:
                failed_feeds.append(source_name)
                self.logger.error(f"Failed to fetch RSS feed {source_name}: {e}")
                continue
        
        # Log summary
        self.logger.info(f"RSS collection complete: {len(successful_feeds)} successful, {len(failed_feeds)} failed")
        if successful_feeds:
            self.logger.info(f"Successful feeds: {', '.join(successful_feeds)}")
        if failed_feeds:
            self.logger.warning(f"Failed feeds: {', '.join(failed_feeds)}")
        
        return articles

    def collect_from_newsapi(self, hours_back: int = 24) -> List[Article]:
        """Collect articles from NewsAPI with thumbnail support"""
        if not self.newsapi_key:
            self.logger.warning("NewsAPI key not provided, skipping NewsAPI collection")
            return []
        
        articles = []
        from_date = (datetime.now(timezone.utc) - timedelta(hours=hours_back)).strftime('%Y-%m-%d')
        
        for keyword in self.lgbtq_keywords[:5]:
            try:
                url = "https://newsapi.org/v2/everything"
                params = {
                    'q': keyword,
                    'from': from_date,
                    'sortBy': 'publishedAt',
                    'language': 'en',
                    'apiKey': self.newsapi_key,
                    'pageSize': 20
                }
                
                response = self.session.get(url, params=params)
                response.raise_for_status()
                
                data = response.json()
                
                for article_data in data.get('articles', []):
                    try:
                        if not article_data.get('content') or article_data['content'] == '[Removed]':
                            continue
                        
                        pub_date = datetime.fromisoformat(
                            article_data['publishedAt'].replace('Z', '+00:00')
                        )
                        
                        thumbnail_url = article_data.get('urlToImage')
                        
                        article = Article(
                            title=article_data['title'],
                            content=article_data['description'] or article_data['content'],
                            url=article_data['url'],
                            published_date=pub_date,
                            source=article_data['source']['name'],
                            thumbnail_url=thumbnail_url
                        )
                        
                        articles.append(article)
                        
                    except Exception as e:
                        self.logger.error(f"Error processing NewsAPI article: {e}")
                        continue
                
                time.sleep(2)
                
            except Exception as e:
                self.logger.error(f"Error fetching from NewsAPI with keyword '{keyword}': {e}")
                continue
        
        return articles

    def collect_all_sources(self, hours_back: int = 24, exclude_keywords: List[str] = None) -> List[Article]:
        """Collect from all available sources with improved resilience"""
        all_articles = []
        
        rss_articles = self.collect_from_rss_with_resilience(hours_back)
        all_articles.extend(rss_articles)
        self.logger.info(f"Collected {len(rss_articles)} articles from RSS feeds")
        
        news_articles = self.collect_from_newsapi(hours_back)
        all_articles.extend(news_articles)
        self.logger.info(f"Collected {len(news_articles)} articles from NewsAPI")
        
        unique_articles = self._deduplicate_articles(all_articles)
        self.logger.info(f"After deduplication: {len(unique_articles)} unique articles")
        
        filtered_articles = self.filter_articles_by_keywords(unique_articles, exclude_keywords)
        self.logger.info(f"After keyword filtering: {len(filtered_articles)} articles")
        
        return filtered_articles

    def generate_google_news_url(self, query: str, language: str = 'en-US', country: str = 'US') -> str:
        """Generate a proper Google News RSS URL from a search query"""
        encoded_query = urllib.parse.quote_plus(query)
        return f'https://news.google.com/rss/search?q={encoded_query}&hl={language}&gl={country}&ceid={country}%3A{language.split("-")[0]}'

    def _parse_date(self, entry) -> Optional[datetime]:
        """Parse date from RSS entry with timezone handling"""
        date_fields = ['published_parsed', 'updated_parsed']
        
        for field in date_fields:
            if hasattr(entry, field) and getattr(entry, field):
                try:
                    time_struct = getattr(entry, field)
                    # Create timezone-aware datetime (assume UTC for RSS feeds)
                    dt = datetime(*time_struct[:6], tzinfo=timezone.utc)
                    return dt
                except:
                    continue
        
        date_strings = ['published', 'updated']
        for field in date_strings:
            if hasattr(entry, field):
                try:
                    from dateutil import parser
                    # Handle timezone parsing with EDT/EST mapping
                    tzinfos = {
                        'EDT': timezone(timedelta(hours=-4)),  # Eastern Daylight Time
                        'EST': timezone(timedelta(hours=-5)),  # Eastern Standard Time
                        'PDT': timezone(timedelta(hours=-7)),  # Pacific Daylight Time
                        'PST': timezone(timedelta(hours=-8)),  # Pacific Standard Time
                        'CDT': timezone(timedelta(hours=-5)),  # Central Daylight Time
                        'CST': timezone(timedelta(hours=-6)),  # Central Standard Time
                        'MDT': timezone(timedelta(hours=-6)),  # Mountain Daylight Time
                        'MST': timezone(timedelta(hours=-7)),  # Mountain Standard Time
                    }
                    dt = parser.parse(getattr(entry, field), tzinfos=tzinfos)
                    # Ensure timezone-aware
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt
                except:
                    continue
        
        return None

    def _extract_content(self, entry) -> str:
        """Extract and clean content from RSS entry"""
        content_fields = ['content', 'summary', 'description']
        
        for field in content_fields:
            if hasattr(entry, field):
                content = getattr(entry, field)
                if isinstance(content, list) and content:
                    raw_content = content[0].get('value', '')
                elif isinstance(content, str):
                    raw_content = content
                else:
                    continue
                
                # Clean HTML tags and return clean text
                return self._clean_html_content(raw_content)
        
        return ""

    def _clean_html_content(self, html_content: str) -> str:
        """Remove HTML tags and clean up content"""
        if not html_content:
            return ""
        
        # Parse HTML and extract text
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.decompose()
        
        # Get text and clean it up
        text = soup.get_text()
        
        # Clean up whitespace
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = ' '.join(chunk for chunk in chunks if chunk)
        
        return text

    def _deduplicate_articles(self, articles: List[Article]) -> List[Article]:
        """Remove duplicate articles based on hash_id"""
        seen_hashes = set()
        unique_articles = []
        
        for article in articles:
            if article.hash_id not in seen_hashes:
                seen_hashes.add(article.hash_id)
                unique_articles.append(article)
        
        return unique_articles

# Flask App
app = Flask(__name__)
collector = LGBTQNewsCollector()

@app.route('/')
def index():
    """Main page displaying recent LGBTQ+ news articles"""
    hours_back = request.args.get('hours', 24, type=int)
    exclude_param = request.args.get('exclude', '')
    
    # Parse exclude keywords from comma-separated string
    exclude_keywords = [kw.strip() for kw in exclude_param.split(',') if kw.strip()] if exclude_param else None
    
    articles = collector.collect_all_sources(hours_back=hours_back, exclude_keywords=exclude_keywords)
    
    # Sort by publication date (newest first) with normalized datetimes
    articles.sort(key=lambda x: collector.normalize_datetime(x.published_date), reverse=True)
    
    return render_template('news.html', 
                         articles=articles, 
                         hours_back=hours_back, 
                         exclude_keywords=exclude_param,
                         default_excluded=','.join(collector.default_excluded_keywords))

@app.route('/api/articles')
def api_articles():
    """API endpoint to get articles in JSON format"""
    hours_back = request.args.get('hours', 24, type=int)
    exclude_param = request.args.get('exclude', '')
    
    # Parse exclude keywords from comma-separated string
    exclude_keywords = [kw.strip() for kw in exclude_param.split(',') if kw.strip()] if exclude_param else None
    
    articles = collector.collect_all_sources(hours_back=hours_back, exclude_keywords=exclude_keywords)
    
    articles_data = []
    for article in articles:
        articles_data.append({
            'title': article.title,
            'content': article.content,
            'url': article.url,
            'published_date': article.published_date.isoformat(),
            'source': article.source,
            'thumbnail_url': article.thumbnail_url,
            'hash_id': article.hash_id
        })
    
    return jsonify({
        'articles': articles_data,
        'count': len(articles_data),
        'excluded_keywords': exclude_keywords or []
    })

@app.route('/refresh')
def refresh():
    """Force refresh of articles"""
    return redirect('/')

# Admin endpoints for feed monitoring
@app.route('/admin')
def admin_dashboard():
    """Simple admin dashboard"""
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>The Brain - Admin Dashboard</title>
        <style>
            body { 
                font-family: Arial, sans-serif; 
                margin: 40px; 
                background-color: #f5f5f5; 
            }
            .container { 
                max-width: 1200px; 
                margin: 0 auto; 
                background: white; 
                padding: 30px; 
                border-radius: 10px; 
                box-shadow: 0 2px 10px rgba(0,0,0,0.1); 
            }
            .status-healthy { color: #28a745; font-weight: bold; }
            .status-unhealthy { color: #dc3545; font-weight: bold; }
            button { 
                padding: 12px 20px; 
                margin: 8px; 
                background: #007bff;
                color: white;
                border: none;
                border-radius: 5px;
                cursor: pointer;
                font-size: 14px;
            }
            button:hover { background: #0056b3; }
            .results { 
                margin-top: 20px; 
                padding: 20px; 
                background: #f8f9fa; 
                border-radius: 5px; 
                border-left: 4px solid #007bff; 
            }
            .feed-list { list-style: none; padding: 0; }
            .feed-item { 
                background: white; 
                margin: 10px 0; 
                padding: 15px; 
                border-radius: 5px; 
                border: 1px solid #dee2e6; 
            }
            .feed-url { color: #6c757d; font-size: 12px; word-break: break-all; }
            .header { color: #495057; border-bottom: 2px solid #007bff; padding-bottom: 10px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1 class="header">🧠 The Brain - Feed Administration</h1>
            
            <h2>Feed Health Monitoring</h2>
            <p>Monitor and test your LGBTQ+ news feed sources for "The Brain" project.</p>
            
            <div style="margin: 20px 0;">
                <button onclick="checkFeedHealth()">🔍 Check All Feeds Health</button>
                <button onclick="listFeeds()">📝 List All Feeds</button>
                <button onclick="showStats()">📊 Show Statistics</button>
            </div>
            
            <div id="results" class="results" style="display: none;"></div>
        </div>
        
        <script>
            function showResults() {
                document.getElementById('results').style.display = 'block';
            }
            
            function checkFeedHealth() {
                showResults();
                document.getElementById('results').innerHTML = '<p>🔄 Checking feed health...</p>';
                
                fetch('/admin/feed-health')
                    .then(response => response.json())
                    .then(data => {
                        let healthyList = data.healthy_feed_list.length > 0 
                            ? data.healthy_feed_list.join(', ') 
                            : 'None';
                        let unhealthyList = data.unhealthy_feed_list.length > 0 
                            ? data.unhealthy_feed_list.join(', ') 
                            : 'None';
                            
                        document.getElementById('results').innerHTML = `
                            <h3>📊 Feed Health Report</h3>
                            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin: 20px 0;">
                                <div style="text-align: center; padding: 20px; background: #d4edda; border-radius: 10px;">
                                    <h4 style="margin: 0; color: #155724;">✅ Healthy Feeds</h4>
                                    <div style="font-size: 2em; color: #28a745; margin: 10px 0;">${data.healthy_feeds}</div>
                                </div>
                                <div style="text-align: center; padding: 20px; background: #f8d7da; border-radius: 10px;">
                                    <h4 style="margin: 0; color: #721c24;">❌ Unhealthy Feeds</h4>
                                    <div style="font-size: 2em; color: #dc3545; margin: 10px 0;">${data.unhealthy_feeds}</div>
                                </div>
                            </div>
                            <p><strong>Total Feeds:</strong> ${data.total_feeds}</p>
                            <p><strong>Healthy Feeds:</strong> <span class="status-healthy">${healthyList}</span></p>
                            <p><strong>Unhealthy Feeds:</strong> <span class="status-unhealthy">${unhealthyList}</span></p>
                            <p><small>Last checked: ${new Date(data.timestamp).toLocaleString()}</small></p>
                        `;
                    })
                    .catch(error => {
                        document.getElementById('results').innerHTML = '<p style="color: red;">❌ Error checking feed health: ' + error + '</p>';
                    });
            }
            
            function listFeeds() {
                showResults();
                document.getElementById('results').innerHTML = '<p>🔄 Loading feed list...</p>';
                
                fetch('/admin/feeds')
                    .then(response => response.json())
                    .then(data => {
                        let html = '<h3>📰 All Configured News Feeds</h3><ul class="feed-list">';
                        data.feeds.forEach(feed => {
                            let typeIcon = feed.type === 'google_news' ? '🔍' : '📡';
                            html += `
                                <li class="feed-item">
                                    <div style="display: flex; justify-content: space-between; align-items: center;">
                                        <div>
                                            <strong>${typeIcon} ${feed.name}</strong> 
                                            <span style="background: #e9ecef; padding: 2px 8px; border-radius: 12px; font-size: 11px; margin-left: 10px;">${feed.type}</span>
                                            <div class="feed-url">${feed.url}</div>
                                        </div>
                                        <button onclick="testFeed('${feed.name}')" style="margin: 0;">🧪 Test</button>
                                    </div>
                                </li>
                            `;
                        });
                        html += '</ul>';
                        document.getElementById('results').innerHTML = html;
                    })
                    .catch(error => {
                        document.getElementById('results').innerHTML = '<p style="color: red;">❌ Error loading feeds: ' + error + '</p>';
                    });
            }
            
            function testFeed(feedName) {
                if (confirm(`Test feed: ${feedName}?`)) {
                    fetch(`/admin/test-feed/${feedName}`)
                        .then(response => response.json())
                        .then(data => {
                            let status = data.error ? '❌ FAILED' : '✅ SUCCESS';
                            let details = data.error 
                                ? `Error: ${data.error}`
                                : `Found ${data.entries_found} entries\\nFetch time: ${data.fetch_time_seconds}s\\nFeed title: ${data.feed_title}`;
                            alert(`${status}\\n\\nFeed: ${data.feed_name}\\n${details}`);
                        })
                        .catch(error => {
                            alert(`❌ Test failed: ${error}`);
                        });
                }
            }
            
            function showStats() {
                showResults();
                document.getElementById('results').innerHTML = `
                    <h3>📈 The Brain Statistics</h3>
                    <p>🎯 <strong>Project:</strong> LGBTQ+ News Aggregator</p>
                    <p>🔧 <strong>Status:</strong> Development/Testing Phase</p>
                    <p>📡 <strong>Sources:</strong> ${Object.keys(${JSON.stringify(Object.keys(collector.rss_feeds))}).length} RSS feeds + NewsAPI</p>
                    <p>🏷️ <strong>Keywords:</strong> ${${JSON.stringify(collector.lgbtq_keywords)}.length} LGBTQ+ focused terms</p>
                    <p>🚫 <strong>Excluded:</strong> ${${JSON.stringify(collector.default_excluded_keywords)}.length} negative keywords filtered</p>
                    <p>⚡ <strong>Features:</strong> Thumbnail extraction, deduplication, timezone handling</p>
                `;
            }
        </script>
    </body>
    </html>
    '''

@app.route('/admin/feed-health')
def admin_feed_health():
    """API endpoint to check feed health status"""
    feed_health = collector.validate_feed_health()
    
    healthy_feeds = [name for name, status in feed_health.items() if status]
    unhealthy_feeds = [name for name, status in feed_health.items() if not status]
    
    return jsonify({
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'total_feeds': len(feed_health),
        'healthy_feeds': len(healthy_feeds),
        'unhealthy_feeds': len(unhealthy_feeds),
        'healthy_feed_list': healthy_feeds,
        'unhealthy_feed_list': unhealthy_feeds,
        'feed_details': feed_health
    })

@app.route('/admin/feeds')
def admin_list_feeds():
    """API endpoint to list all configured feeds"""
    return jsonify({
        'feeds': [
            {
                'name': name,
                'url': url,
                'type': 'google_news' if 'news.google.com' in url else 'standard_rss'
            }
            for name, url in collector.rss_feeds.items()
        ]
    })

@app.route('/admin/test-feed/<feed_name>')
def admin_test_single_feed(feed_name):
    """Test a specific feed and return detailed results"""
    if feed_name not in collector.rss_feeds:
        return jsonify({'error': 'Feed not found'}), 404
    
    feed_url = collector.rss_feeds[feed_name]
    
    try:
        start_time = time.time()
        
        feed = collector._fetch_and_fix_feed(feed_url, feed_name)
        
        fetch_time = time.time() - start_time
        
        return jsonify({
            'feed_name': feed_name,
            'feed_url': feed_url,
            'fetch_time_seconds': round(fetch_time, 2),
            'entries_found': len(feed.entries) if feed.entries else 0,
            'feed_title': getattr(feed.feed, 'title', 'Unknown') if hasattr(feed, 'feed') else 'Unknown',
            'last_updated': getattr(feed.feed, 'updated', 'Unknown') if hasattr(feed, 'feed') else 'Unknown',
            'has_bozo_error': hasattr(feed, 'bozo') and feed.bozo,
            'bozo_exception': str(feed.bozo_exception) if hasattr(feed, 'bozo_exception') else None,
            'sample_titles': [entry.title for entry in feed.entries[:3]] if feed.entries else []
        })
        
    except Exception as e:
        return jsonify({
            'feed_name': feed_name,
            'feed_url': feed_url,
            'error': str(e),
            'status': 'failed'
        }), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)