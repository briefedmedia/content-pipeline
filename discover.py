# discover.py -- two-stage story discovery for Briefed
#
# STAGE 1: Pull today's most significant headlines from multiple nonpartisan
#           RSS sources. Claude deduplicates and ranks by significance.
#
# STAGE 2: For each top headline, Claude builds layered historical context
#           using its own knowledge first, then Wikipedia adds verified facts.
#           Three layers:
#             - Immediate causes (last 1-5 years)
#             - Deeper history (5+ years ago)
#             - Why it matters to a 25-year-old today
#
# This output is what script.py uses to write the Briefed video script.

import os
import json
import datetime
import requests
import feedparser
import anthropic
from dotenv import load_dotenv
from drive import upload_file
from config import TMP, CLAUDE_MODEL

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


# ── RSS Sources ────────────────────────────────────────────────────────────────
# All verified working. All free, no API keys required.
# Google News RSS aggregates AP, Reuters, and all major outlets -- no Cloudflare.

RSS_SOURCES = [
    # ── Google News aggregators (pulls from AP, Reuters, NYT, WaPo, etc.) ──
    {
        "name":   "Google News - World",
        "url":    "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en",
        "weight": 1.3,
        "note":   "Aggregates all major wire services -- most comprehensive",
    },
    {
        "name":   "Google News - US",
        "url":    "https://news.google.com/rss/headlines/section/topic/NATION?hl=en-US&gl=US&ceid=US:en",
        "weight": 1.2,
    },

    # ── Direct RSS feeds -- verified no Cloudflare blocking ──
    {
        "name":   "Reuters World",
        "url":    "https://news.google.com/rss/search?q=site%3Areuters.com&hl=en-US&gl=US&ceid=US%3Aen",
        "weight": 1.3,
        "note":   "Wire service -- primary source",
    },
    {
        "name":   "BBC World News",
        "url":    "https://feeds.bbci.co.uk/news/world/rss.xml",
        "weight": 1.2,
    },
    {
        "name":   "Sky News World",
        "url":    "https://feeds.skynews.com/feeds/rss/world.xml",
        "weight": 1.0,
    },
    {
        "name":   "NPR News",
        "url":    "https://feeds.npr.org/1001/rss.xml",
        "weight": 1.0,
    },
    {
        "name":   "PBS NewsHour",
        "url":    "https://www.pbs.org/newshour/feeds/rss/headlines",
        "weight": 1.0,
    },
    {
        "name":   "Washington Post World",
        "url":    "https://feeds.washingtonpost.com/rss/world",
        "weight": 1.0,
    },
    {
        "name":   "Politico",
        "url":    "https://feeds.feedburner.com/politico/politics",
        "weight": 0.9,
    },
    {
        "name":   "Al Jazeera English",
        "url":    "https://www.aljazeera.com/xml/rss/all.xml",
        "weight": 0.9,
        "note":   "Strong Middle East / Global South coverage",
    },
]

HEADLINES_PER_SOURCE   = 7
TOP_STORIES_TO_ENRICH  = 8


# ── Utility: strip markdown code fences from Claude responses ─────────────────

def strip_fences(text):
    """Remove ```json ... ``` or ``` ... ``` wrappers Claude sometimes adds."""
    text = text.strip()
    if text.startswith("```"):
        # Remove first line (```json or ```)
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    return text.strip()


# ── Stage 1: Fetch headlines ───────────────────────────────────────────────────

def fetch_rss(source):
    """Fetch headlines from one RSS source using browser-like headers."""
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        }
        response = requests.get(source["url"], headers=headers, timeout=15)
        feed     = feedparser.parse(response.text)

        if not feed.entries:
            print(f"  {source['name']}: no entries (may be blocked)")
            return []

        stories = []
        for entry in feed.entries[:HEADLINES_PER_SOURCE]:
            # Clean HTML from summaries (Google News wraps in <a> tags)
            raw_summary = entry.get("summary", entry.get("description", ""))
            import re
            clean_summary = re.sub(r"<[^>]+>", "", raw_summary).strip()

            stories.append({
                "source":    source["name"],
                "weight":    source.get("weight", 1.0),
                "title":     entry.get("title", "").strip(),
                "summary":   clean_summary[:400],
                "url":       entry.get("link", ""),
                "published": entry.get("published", ""),
            })

        print(f"  {source['name']}: {len(stories)} headlines")
        return stories

    except Exception as e:
        print(f"  {source['name']}: failed -- {e}")
        return []


def fetch_all_headlines():
    """Pull headlines from all RSS sources."""
    print("Stage 1: Fetching headlines...")
    all_stories = []
    for source in RSS_SOURCES:
        stories = fetch_rss(source)
        all_stories.extend(stories)
    print(f"  Total: {len(all_stories)} headlines from {len(RSS_SOURCES)} sources")
    return all_stories


# ── Stage 1b: Deduplicate and rank ────────────────────────────────────────────

RANKING_PROMPT = """You are the senior editor of Briefed, a nonpartisan current events channel for young adults (18-30).

You will receive a list of news headlines from multiple sources today.

Your tasks:
1. DEDUPLICATE -- many sources cover the same event. Pick the best-written version.
2. FILTER OUT -- sports results, celebrity gossip, entertainment, purely local stories
3. RANK -- order by significance AND how much historical depth the story has
4. IDENTIFY WIKIPEDIA TERMS -- for each story, give 2-3 specific Wikipedia article
   titles (not search queries -- actual likely article titles) that cover the
   UNDERLYING HISTORY, not the current event itself.

   Good example:
   Headline: "Israel declares occupation of southern Lebanon buffer zone"
   Wikipedia terms: ["2006 Lebanon War", "United Nations Security Council Resolution 1701", "Hezbollah"]

   Bad example (too literal):
   Headline: "Israel declares occupation of southern Lebanon buffer zone"
   Wikipedia terms: ["Israel Lebanon occupation 2026"] -- this article won't exist

Prioritize stories with rich historical depth. Iran-Israel conflict, Russia-Ukraine,
immigration policy, economic crises -- these have decades of history to draw on.

Return ONLY raw JSON with no markdown fences, no preamble:
{
  "top_stories": [
    {
      "rank": 1,
      "title": "clean readable headline",
      "summary": "2-3 sentence factual summary of what happened today",
      "source": "source name",
      "url": "article url",
      "significance": "one sentence -- why this matters to ordinary people",
      "wikipedia_terms": ["Article Title One", "Article Title Two", "Article Title Three"]
    }
  ]
}"""


def rank_headlines(all_stories):
    """Use Claude to deduplicate and rank headlines."""
    print("\nStage 1b: Ranking with Claude...")

    story_list = [
        {
            "id":      i,
            "source":  s["source"],
            "weight":  s["weight"],
            "title":   s["title"],
            "summary": s["summary"] or "(no summary)",
            "url":     s["url"],
        }
        for i, s in enumerate(all_stories)
    ]

    msg = client.messages.create(
        model      = CLAUDE_MODEL,
        max_tokens = 8000,
        system     = RANKING_PROMPT,
        messages   = [{"role": "user", "content": json.dumps(story_list, indent=2)}]
    )

    raw = strip_fences(msg.content[0].text)
    print(f"  After stripping, first 100 chars: {repr(raw[:100])}")

    try:
        ranked  = json.loads(raw)
        stories = ranked["top_stories"]
        print(f"  Selected {len(stories)} stories from {len(all_stories)} headlines")
        if stories:
            print(f"  First story keys: {list(stories[0].keys())}")
            print(f"  Wikipedia key value: {stories[0].get('wikipedia_terms', 'KEY NOT FOUND')}")
        return stories

    except json.JSONDecodeError as e:
        print(f"  Ranking parse failed: {e}")

        # Fallback: top stories by source weight, deduplicated
        seen, fallback = set(), []
        for s in sorted(all_stories, key=lambda x: x["weight"], reverse=True):
            key = s["title"].lower()[:60]
            if key not in seen:
                seen.add(key)
                fallback.append({
                    "rank":            len(fallback) + 1,
                    "title":           s["title"],
                    "summary":         s["summary"] or s["title"],
                    "source":          s["source"],
                    "url":             s["url"],
                    "significance":    "Selected by source weight",
                    "wikipedia_terms": [],   # empty -- enrichment will handle
                })
                if len(fallback) >= TOP_STORIES_TO_ENRICH:
                    break
        return fallback


# ── Stage 2: Layered historical enrichment ────────────────────────────────────

def fetch_wikipedia_article(title):
    """Fetch the intro section of a specific Wikipedia article by title."""
    try:
        resp = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params = {
                "action":      "query",
                "prop":        "extracts",
                "exintro":     True,
                "explaintext": True,
                "titles":      title,
                "format":      "json",
                "redirects":   1,
            },
            headers = {"User-Agent": "BriefedMedia/1.0 (contact@briefedmedia.com)"},
            timeout = 10,
        )
        pages   = resp.json().get("query", {}).get("pages", {})
        page    = next(iter(pages.values()))

        # -1 means article not found
        if page.get("pageid", -1) == -1:
            return None

        extract = page.get("extract", "").strip()
        if not extract:
            return None

        return {
            "title":   page.get("title", title),
            "extract": extract[:3000],
            "url":     f"https://en.wikipedia.org/wiki/{page.get('title', title).replace(' ', '_')}",
        }

    except Exception as e:
        print(f"    Wikipedia fetch failed for '{title}': {e}")
        return None


def search_wikipedia_fallback(query):
    """Search Wikipedia when exact article title doesn't exist."""
    try:
        resp = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params = {
                "action":   "query",
                "list":     "search",
                "srsearch": query,
                "srlimit":  2,
                "format":   "json",
            },
            headers = {"User-Agent": "BriefedMedia/1.0 (contact@briefedmedia.com)"},
            timeout = 10,
        )
        results = resp.json().get("query", {}).get("search", [])
        if not results:
            return None

        # Try fetching the top result
        return fetch_wikipedia_article(results[0]["title"])

    except Exception as e:
        print(f"    Wikipedia search failed for '{query}': {e}")
        return None


# The enrichment prompt -- Claude reasons from its own knowledge first
ENRICHMENT_PROMPT = """You are a research editor for Briefed, a nonpartisan current events channel.

You will receive:
1. A current news headline and summary
2. Wikipedia article extracts on related historical topics (may be empty)

Your job is to build layered historical context that explains WHY this story is
happening. Use your own knowledge as the primary source. Use the Wikipedia
extracts to add specific verified dates, names, and facts.

Build THREE LAYERS of context:

LAYER 1 -- IMMEDIATE CAUSES (last 1-5 years):
What specific recent events directly led to this headline?
Be concrete -- name actual events, decisions, and turning points.
Example: "The current conflict stems directly from Hamas's October 7, 2023 attack,
which killed 1,200 Israelis and triggered Israel's military campaign in Gaza and
Lebanon, which in turn drew in Iran through its proxy networks."

LAYER 2 -- DEEPER HISTORY (5+ years ago):
What foundational history explains why those recent events were possible?
Key conflicts, agreements, power structures, or decisions from the past.
Example: "Israel and Lebanon have a long conflict history -- Israel occupied
southern Lebanon from 1982 to 2000, during which time Hezbollah grew from a
small militia into a major military force with 150,000 rockets."

LAYER 3 -- WHY A 25-YEAR-OLD SHOULD CARE:
One concrete, personal way this affects ordinary Americans or global citizens.
NOT abstract geopolitics -- real impact on real life.
Example: "The Strait of Hormuz -- which Iran has threatened to close -- carries
20% of the world's oil. A closure would spike US gas prices within days."

SUGGESTED HOOK:
One surprising or counterintuitive historical fact that most people don't know
but that genuinely reframes how they see this story. This should be the opening
line of a Briefed video -- something that makes someone stop scrolling.
Example: "The US actually sold Iran the F-14 fighter jets it's now using against
American allies -- a deal made in 1974 when Iran was a close US ally."

Return ONLY raw JSON with no markdown fences, no preamble:
{
  "layer1_immediate": "2-4 sentences on direct recent causes",
  "layer2_history": "2-4 sentences on deeper foundational history",
  "layer3_stakes": "1-2 sentences on personal stakes for ordinary people",
  "key_events": [
    {"year": "YYYY", "event": "one clear sentence"},
    {"year": "YYYY", "event": "one clear sentence"},
    {"year": "YYYY", "event": "one clear sentence"}
  ],
  "suggested_hook": "one surprising fact that stops the scroll",
  "explainability_score": 8
}

The explainability_score (1-10) rates how well this story can be explained
with historical context. 10 = rich history, easy to explain. 1 = too recent
or too technical to add meaningful background."""


def enrich_with_history(story):
    """Build layered historical context for a story using Claude + Wikipedia."""
    print(f"\n  Enriching: {story['title'][:70]}...")

    # Step 1: Fetch Wikipedia articles using the terms Claude identified
    wiki_articles = []
    wikipedia_terms = story.get("wikipedia_terms", [])

    if not wikipedia_terms:
        print(f"    No Wikipedia terms -- Claude will rely on own knowledge")
    else:
        for term in wikipedia_terms:
            print(f"    Wikipedia: '{term}'")
            # Try exact title first, fall back to search
            article = fetch_wikipedia_article(term)
            if not article:
                print(f"    Not found by title, trying search...")
                article = search_wikipedia_fallback(term)
            if article:
                wiki_articles.append(article)
                print(f"    Found: '{article['title']}'")
            else:
                print(f"    No article found for '{term}'")

    # Step 2: Build context package for Claude
    context = {
        "headline":           story["title"],
        "summary":            story["summary"],
        "wikipedia_articles": [
            {"title": a["title"], "content": a["extract"]}
            for a in wiki_articles
        ],
    }

    # Step 3: Claude builds layered context using own knowledge + Wikipedia
    msg = client.messages.create(
        model      = CLAUDE_MODEL,
        max_tokens = 1500,
        system     = ENRICHMENT_PROMPT,
        messages   = [{"role": "user", "content": json.dumps(context, indent=2)}]
    )

    raw = strip_fences(msg.content[0].text)

    try:
        enrichment = json.loads(raw)
        story["historical_context"] = enrichment
        story["wikipedia_sources"]  = [a["url"] for a in wiki_articles]
        score = enrichment.get("explainability_score", "?")
        hook  = enrichment.get("suggested_hook", "")[:80]
        print(f"    Score: {score}/10 | Hook: {hook}...")
    except json.JSONDecodeError as e:
        print(f"    Parse failed: {e}")
        print(f"    Raw preview: {raw[:200]}")
        story["historical_context"] = None

    return story


# ── Main entry point ───────────────────────────────────────────────────────────

def run_discovery():
    """Full two-stage discovery. Returns enriched candidates saved to Drive."""
    today    = datetime.date.today().isoformat()
    filename = f"candidates_{today}.json"

    # Stage 1
    all_headlines  = fetch_all_headlines()
    if not all_headlines:
        print("ERROR: No headlines fetched. Check network and RSS URLs.")
        return []

    ranked_stories = rank_headlines(all_headlines)

    # Stage 2
    print(f"\nStage 2: Enriching top {TOP_STORIES_TO_ENRICH} stories...")
    enriched = []
    for story in ranked_stories[:TOP_STORIES_TO_ENRICH]:
        enriched.append(enrich_with_history(story))

    # Filter out stories below minimum explainability threshold
    from config import MIN_EXPLAINABILITY_SCORE
    qualified   = []
    unqualified = []

    for story in enriched:
        score = 0
        if story.get("historical_context"):
            score = story["historical_context"].get("explainability_score", 0)
        if score >= MIN_EXPLAINABILITY_SCORE:
            qualified.append(story)
        else:
            unqualified.append(story)

    if unqualified:
        print(f"\n  Filtered out {len(unqualified)} low-scoring stories:")
        for s in unqualified:
            score = s.get("historical_context", {}).get("explainability_score", 0)
            print(f"    [{score}/10] {s['title'][:60]}")

    # Replace enriched with only qualified stories
    enriched = qualified

    # Save to Drive
    output = {
        "date":            today,
        "sources_checked": len(RSS_SOURCES),
        "total_headlines": len(all_headlines),
        "candidates":      enriched,
    }

    local_path = os.path.join(TMP, filename)
    with open(local_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    file_id = upload_file(local_path, "stories", filename)

    # Print summary
    print(f"\n{'─' * 65}")
    print(f"Discovery complete -- {len(enriched)} stories | Drive ID: {file_id}")
    print(f"{'─' * 65}")

    for s in enriched:
        ctx  = s.get("historical_context") or {}
        hook = ctx.get("suggested_hook", "(no hook)")
        score = ctx.get("explainability_score", "?")
        print(f"\n{s['rank']}. [{score}/10] {s['title']}")
        print(f"   {s.get('significance', '')}")
        print(f"   Hook: {hook}")

    return enriched


# ── Test block ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Running Briefed discovery pipeline...\n")
    candidates = run_discovery()
    print(f"\nDone. {len(candidates)} enriched candidates ready for script.py.")