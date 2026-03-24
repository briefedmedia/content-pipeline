# discover.py -- run continuously, checks sources every 30 minutes
import requests, json, datetime, feedparser, time, os
from drive import upload_file
from script import check_for_breaking
from config import TMP

NEWSAPI_KEY = "58bef030b72d44539e91089b87852014"
BREAKING_THRESHOLD = 7  # urgency score out of 10 to trigger alert

def fetch_wikipedia_onthisday():
    today = datetime.date.today()
    url = f"https://api.wikimedia.org/feed/v1/wikipedia/en/onthisday/events/{today.month}/{today.day}"
    r = requests.get(url, headers={"User-Agent": "ContentPipeline/1.0"})
    events = r.json().get("events", [])
    return [{"source": "wikipedia", "title": e["pages"][0]["title"],
             "summary": e["pages"][0]["extract"], "year": e["year"]}
            for e in events[:10] if e.get("pages")]

def fetch_ap_rss():
    feed = feedparser.parse("https://feeds.apnews.com/rss/topnews")
    return [{"source": "ap_news", "title": e.title,
             "summary": e.summary, "url": e.link}
            for e in feed.entries[:10]]

def run_scan():
    candidates = fetch_wikipedia_onthisday() + fetch_ap_rss()
    today = datetime.date.today().isoformat()
    filename = f"candidates_{today}.json"
    filepath = os.path.join(TMP, filename)
    with open(filepath, "w") as f:
        json.dump(candidates, f, indent=2)
    upload_file(filepath, "stories", filename)
    # Check each candidate for breaking news status
    for story in candidates:
        check_for_breaking(story, account_type="news")
    return candidates

if __name__ == "__main__":
    print("Scanner running -- checking every 30 minutes...")
    while True:
        try:
            run_scan()
        except Exception as e:
            print(f"Scan error: {e}")
        time.sleep(1800)  # 30 minutes