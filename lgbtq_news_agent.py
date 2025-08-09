import feedparser
import openai
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

# LGBTQ+ RSS Feeds (add more if needed)
rss_feeds = [
    "https://www.lgbtqnation.com/feed/",
    "https://www.advocate.com/rss.xml",
    "https://www.pinknews.co.uk/feed/",
    "https://queerty.com/feed",
    "https://out.com/feeds/news.rss",
    "http://metroweekly.com/feed",
    "http://ebar.com/feed",
    "http://losangelesblade.com/feed",
    "https://outsports.com/feed",
    "https://gaytimes.com/feed",
    "https://glaad.org/feed",
    "https://roughdraftatlanta.com/georgiavoice/",
    "https://news.google.com/search?q=gay%20atlanta%20-matt%20-jazz&hl=en-US&gl=US&ceid=US%3Aen",
    "https://news.google.com/topics/CAAqIQgKIhtDQkFTRGdvSUwyMHZNR2h1TVRBU0FtVnVLQUFQAQ?hl=en-US&gl=US&ceid=US%3Aen",
    "https://www.washingtonblade.com/feed/",
    "https://www.theguardian.com/world/lgbt-rights/rss"
]

def fetch_headlines():
    """Fetch and compile top headlines from LGBTQ+ RSS feeds."""
    articles = []
    for url in rss_feeds:
        feed = feedparser.parse(url)
        for entry in feed.entries[:3]:  # Top 3 per source
            articles.append({
                "title": entry.title,
                "link": entry.link,
                "summary": entry.summary
            })
    return articles

def summarize_articles(articles):
    """Use GPT to summarize articles into a news digest."""
    content = "\n\n".join(
        f"{i+1}. {a['title']}\n{a['summary']}\nLink: {a['link']}"
        for i, a in enumerate(articles)
    )
    
    prompt = f"""Summarize the following LGBTQ+ news headlines and brief summaries into a concise, professional daily digest. Group related stories and write in a newsletter tone.\n\n{content}"""

    client = OpenAI()

    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=2000
    )

    return response.choices[0].message.content


    return response.choices[0].message["content"]

def main():
    print("📡 Fetching LGBTQ+ news...")
    articles = fetch_headlines()
    
    print("🧠 Summarizing with GPT...")
    summary = summarize_articles(articles)
    
    print("\n📨 Daily LGBTQ+ News Summary:\n")
    print(summary)

if __name__ == "__main__":
    main()
