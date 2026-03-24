# script.py -- four-call pipeline with word count validation
import anthropic, json, datetime, os
from dotenv import load_dotenv
from drive import upload_file
from config import TMP, CLAUDE_MODEL, MIN_EXPLAINABILITY_SCORE

load_dotenv()

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
WORD_MIN      = 155   # 62 seconds -- hard floor, reject below this
WORD_TARGET   = 188   # 75 seconds -- natural aim
WORD_SOFT_CAP = 225   # 90 seconds -- absolute ceiling enforced by quality checker
# No hard ceiling in script writer -- quality checker enforces 225 max.


# ── Selector prompt ────────────────────────────────────────────────────────────

SELECTOR_PROMPT = """You are a video content producer for Briefed, a nonpartisan
current events channel for young adults.

Given these story candidates, pick the SINGLE most compelling one for a
60-90 second explainer video.

Rules:
- NEVER select a story with explainability_score below {min_score}
- Prefer stories with scores of 8 or higher
- A story without rich historical context cannot educate our audience
- If multiple stories score equally, prefer the one most relevant to US audiences

Return JSON only, no markdown fences: {{"index": N, "reason": "...", "title": "..."}}
""".format(min_score=MIN_EXPLAINABILITY_SCORE)


# ── Script writing prompts ─────────────────────────────────────────────────────

HISTORY_SCRIPT_PROMPT = """You are writing narration for a cinematic short-form history video for Briefed.

ABSOLUTE MAXIMUM: 225 words. Non-negotiable. Cut ruthlessly -- every sentence earns its place.
Hard minimum: 155 words. Natural target: 175-200 words.

STRUCTURE (write as continuous narration -- do not label sections):

1. HOOK (1-2 sentences)
   One surprising or counterintuitive historical fact. No context yet.
   Make someone stop scrolling. Start with the most unexpected thing.

2. SETUP (2-3 sentences)
   Who, what, where -- vivid but efficient. Essential context only.

3. THE TURN (3-4 sentences)
   The dramatic conflict or decision point. The moment everything changed.
   Draw from the historical_context provided in the story data.

4. HIDDEN CONTEXT (1-2 sentences)
   One verified fact from the provided historical_context data that mainstream
   coverage consistently omits or underreports.
   Frame as: "What most coverage misses..." or "Here's what the headlines leave out..."
   or "But here's what you probably haven't heard..."
   CRITICAL: Must come directly from the research provided. Never invent or fabricate.
   This should reframe everything the viewer just heard.

5. STAKES (1-2 sentences)
   Concrete impact on ordinary people's lives today. Not abstract geopolitics --
   real impact: prices, jobs, safety, rights.

6. KICKER (1 sentence -- the most important sentence in the script)
   Do NOT use "watch for", "time will tell", "only time will tell", or any
   wire service convention. Those are lazy and forgettable.
   Instead, choose ONE of these three approaches:
   - THE REFRAME: One sentence that makes everything mean something different
     than the viewer thought. "X isn't about Y. It's about Z."
   - THE UNRESOLVED QUESTION: A question the video raised but cannot answer --
     one with no easy resolution that demands further thought.
   - THE CALLBACK WITH TWIST: Return to the hook but with new meaning now that
     the viewer has the full context.
   Model: NYT Opinion TikTok endings -- curious, slightly unsettling, memorable.
   The viewer should feel something unresolved that makes them want to keep thinking.

Return JSON only, no markdown fences:
{"script": "...", "title": "...", "word_count": N,
 "estimated_seconds": N, "scenes": ["scene 1 desc", ...]}
Scene count = estimated_seconds / 5 (rounded up)."""


NEWS_SCRIPT_PROMPT = """You are writing narration for a non-partisan news explainer for Briefed.

ABSOLUTE MAXIMUM: 225 words. Non-negotiable. Cut ruthlessly -- every sentence earns its place.
Hard minimum: 155 words. Natural target: 175-200 words.

LANGUAGE RULES:
- No emotionally loaded language (radical, extreme, shameful, crisis, etc.)
- Steelman all positions -- present the strongest version of each argument
- Translate all jargon on first use
- Never attribute motive -- describe actions, not intent
- No conclusions -- present facts and let the viewer decide

STRUCTURE (write as continuous narration -- do not label sections):

1. HOOK (1-2 sentences)
   One surprising or counterintuitive fact about this story.
   Not the obvious angle -- the thing that reframes the whole situation.
   Make someone stop scrolling.

2. CURRENT FACTS (2-3 sentences)
   What happened today, stated plainly. No opinion, no framing.

3. HISTORICAL BACKGROUND (3-4 sentences)
   The context that makes today's event make sense.
   Draw from the historical_context provided in the story data.
   If this story requires 4-5 sentences of background to be explained
   honestly, use them -- background has more flexibility than other sections.

4. HIDDEN CONTEXT (1-2 sentences)
   One verified fact from the provided historical_context data that mainstream
   coverage consistently omits or underreports.
   Frame as: "What most coverage misses..." or "Here's what the headlines leave out..."
   or "But here's what you probably haven't heard..."
   CRITICAL: Must come directly from the research provided. Never invent or fabricate.
   This is the most important element of the script -- the inside scoop.
   It should reframe everything the viewer just heard.

5. STAKES (1-2 sentences)
   Concrete impact on ordinary people's lives. Not abstract policy --
   real impact: prices, jobs, safety, rights, daily life.

6. KICKER (1 sentence -- the most important sentence in the script)
   Do NOT use "watch for", "time will tell", or any wire service convention.
   Those are lazy and signal AI-generated slop. Avoid them completely.
   Instead, choose ONE of these three approaches:
   - THE REFRAME: One sentence that makes everything mean something different.
     "X isn't about Y. It's about Z."
   - THE UNRESOLVED QUESTION: A question raised but not answered -- one with
     no easy resolution that leaves the viewer sitting with something.
   - THE CALLBACK WITH TWIST: Return to the hook with new meaning now that
     the viewer has the full context.
   Model: NYT Opinion TikTok endings. Curious, slightly unsettling, memorable.
   The viewer should feel something unresolved that makes them want to keep thinking.

Return JSON only, no markdown fences:
{"script": "...", "title": "...", "word_count": N,
 "estimated_seconds": N, "scenes": ["scene 1 desc", ...]}
Scene count = estimated_seconds / 5 (rounded up)."""


# ── Bias audit prompt ──────────────────────────────────────────────────────────

BIAS_AUDIT_PROMPT = """You are a non-partisan fact-checker reviewing a news explainer script.

Flag any of the following:
- Emotionally loaded language (words that imply judgment rather than describe facts)
- Missing perspectives (a significant viewpoint that is absent or misrepresented)
- Factual errors or unverifiable claims
- Political framing that favors one side

If the script is clean, say so. If not, provide a revised version that fixes
the issues while maintaining or expanding the word count as needed for accuracy.
Do not cut content for brevity -- only for accuracy.

Return JSON only, no markdown fences:
{"clean": true/false, "flags": ["issue 1", "issue 2"], "revised_script": "..."}

Always include revised_script -- either the original if clean, or the corrected version."""


# ── Quality check prompt ───────────────────────────────────────────────────────

QUALITY_CHECK_PROMPT = """You are a quality reviewer for short-form video scripts.

HARD LENGTH LIMIT: 225 words maximum. This is non-negotiable.
If the script exceeds 225 words, you MUST trim it. No exceptions.

When trimming, follow this priority order:
1. Cut adjectives and qualifiers first (they add words, not information)
2. Cut redundant explanations (if a fact is clear, don't restate it)
3. Cut background detail before cutting stakes or hook
4. NEVER cut the hook (first 1-2 sentences)
5. NEVER cut the kicker (last sentence)
6. NEVER cut a fact that changes the meaning of the story

Also evaluate COMPLETENESS: could someone who knew nothing about this topic
explain the full story after watching once? If not, note what's missing --
but do not add words that push over 225. Flag it instead.

Return JSON only, no markdown fences:
{"pass": true/false, "word_count": N, "completeness_verdict": "...",
 "revised_script": "..."}

Always return revised_script -- trimmed version if over 225 words,
original unchanged if already within limit."""


# ── Utility: strip markdown code fences ───────────────────────────────────────

def strip_fences(text):
    """Remove ```json ... ``` wrappers Claude sometimes adds despite instructions."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    return text.strip()


# ── Word count validation ──────────────────────────────────────────────────────

def validate_word_count(script_text):
    count = len(script_text.split())
    if count < WORD_MIN:
        raise ValueError(f"Script too short: {count} words (min {WORD_MIN})")
    if count > WORD_SOFT_CAP:
        print(f"  Note: {count} words -- above soft cap, quality checker will trim")
    return count


# ── Four Claude calls ──────────────────────────────────────────────────────────

def select_story(candidates):
    msg = client.messages.create(
        model      = CLAUDE_MODEL,
        max_tokens = 500,
        system     = SELECTOR_PROMPT,
        messages   = [{"role": "user", "content": json.dumps(candidates)}]
    )
    return json.loads(strip_fences(msg.content[0].text))


def write_script(story, account_type="history"):
    prompt = HISTORY_SCRIPT_PROMPT if account_type == "history" else NEWS_SCRIPT_PROMPT
    msg = client.messages.create(
        model      = CLAUDE_MODEL,
        max_tokens = 2000,
        system     = prompt,
        messages   = [{"role": "user", "content": json.dumps(story)}]
    )
    result = json.loads(strip_fences(msg.content[0].text))

    # Remap alternative key names Claude sometimes uses despite instructions
    if "script" not in result:
        for alt_key in ["narration", "text", "content", "body"]:
            if alt_key in result:
                result["script"] = result.pop(alt_key)
                break
        # If Claude returned sections dict, flatten into one string
        if "script" not in result and "sections" in result:
            parts = []
            for s in result["sections"]:
                if isinstance(s, dict):
                    parts.append(s.get("text", s.get("content", str(s))))
                else:
                    parts.append(str(s))
            result["script"] = " ".join(parts)

    # Ensure all required keys exist with safe defaults
    result.setdefault("title", story.get("title", "Untitled"))
    result.setdefault("scenes", [])
    result.setdefault("word_count", len(result.get("script", "").split()))
    result.setdefault("estimated_seconds", result["word_count"] * 60 // 155)

    validate_word_count(result["script"])
    return result


def audit_bias(script_data, max_retries=3):
    for i in range(max_retries):
        msg = client.messages.create(
            model      = CLAUDE_MODEL,
            max_tokens = 1500,
            system     = BIAS_AUDIT_PROMPT,
            messages   = [{"role": "user", "content": script_data["script"]}]
        )
        audit = json.loads(strip_fences(msg.content[0].text))

        # Remap alternative key names
        if "revised_script" not in audit and "script" in audit:
            audit["revised_script"] = audit["script"]
        if "clean" not in audit:
            audit["clean"] = not bool(audit.get("flags", []))

        if audit["clean"]:
            print(f"  Bias audit passed (attempt {i+1})")
            return script_data
        print(f"  Bias audit flagged {len(audit.get('flags', []))} issues -- revising")
        if audit.get("revised_script"):
            script_data["script"] = audit["revised_script"]
            validate_word_count(script_data["script"])
    return script_data


def quality_check(script_data, max_retries=2):
    for i in range(max_retries):
        msg = client.messages.create(
            model      = CLAUDE_MODEL,
            max_tokens = 1500,
            system     = QUALITY_CHECK_PROMPT,
            messages   = [{"role": "user", "content": script_data["script"]}]
        )
        result = json.loads(strip_fences(msg.content[0].text))

        # Remap alternative key names
        if "pass" not in result:
            for alt_key in ["passed", "approved", "ok"]:
                if alt_key in result:
                    result["pass"] = result[alt_key]
                    break
            result.setdefault("pass", True)
        if "revised_script" not in result and "script" in result:
            result["revised_script"] = result["script"]

        wc = len(script_data["script"].split())

        # Always apply revised_script if provided -- catches length trimming
        if result.get("revised_script"):
            new_wc = len(result["revised_script"].split())
            if new_wc != wc:
                print(f"  Quality check trimmed: {wc} → {new_wc} words")
            script_data["script"] = result["revised_script"]
            script_data["word_count"] = new_wc

        if result["pass"] and len(script_data["script"].split()) <= WORD_SOFT_CAP:
            print(f"  Quality check passed ({len(script_data['script'].split())} words)")
            return script_data

    return script_data


def check_for_breaking(story, account_type="news"):
    """Check if a story qualifies as breaking news (called by scanner)."""
    BREAKING_PROMPT = """You are a news editor. Does this story qualify as BREAKING?
Criteria: happened in last 6 hours, genuinely significant, publishing within
12 hours gives a meaningful first-mover advantage, fits our mission of
context plus historical background. Be conservative.
Reserve urgent for genuine inflection points.
Return JSON only, no markdown fences:
{"breaking": true/false, "urgency": 1-10, "reason": "..."}"""
    msg = client.messages.create(
        model      = CLAUDE_MODEL,
        max_tokens = 300,
        system     = BREAKING_PROMPT,
        messages   = [{"role": "user", "content": json.dumps(story)}]
    )
    result = json.loads(strip_fences(msg.content[0].text))
    if result["breaking"] and result["urgency"] >= 7:
        from breaking import handle_breaking
        handle_breaking(story, result["urgency"], account_type)


# ── Main entry point ───────────────────────────────────────────────────────────

def run_scripting(candidates, account_type="history"):
    # Hard filter -- remove stories below minimum explainability threshold
    qualified = [
        c for c in candidates
        if c.get("historical_context") and
        c["historical_context"].get("explainability_score", 0) >= MIN_EXPLAINABILITY_SCORE
    ]

    if not qualified:
        print(f"  WARNING: No candidates met minimum score of {MIN_EXPLAINABILITY_SCORE}. Using all.")
        qualified = candidates
    else:
        print(f"  {len(qualified)}/{len(candidates)} candidates qualify (score >= {MIN_EXPLAINABILITY_SCORE})")

    selected    = select_story(qualified)
    story       = qualified[selected["index"]]
    print(f"  Selected: {selected['title']}")

    script_data = write_script(story, account_type)

    if account_type == "news":
        script_data = audit_bias(script_data)

    script_data = quality_check(script_data)

    today    = datetime.date.today().isoformat()
    filename = f"script_{today}_{account_type}.json"

    local_json = os.path.join(TMP, filename)
    with open(local_json, "w", encoding="utf-8") as f:
        json.dump(script_data, f, indent=2, ensure_ascii=False)
    fid = upload_file(local_json, "scripts", filename)

    # Plain text version for easy phone reading before recording VO
    local_txt = os.path.join(TMP, f"script_{today}_{account_type}.txt")
    with open(local_txt, "w", encoding="utf-8") as f:
        f.write(f"{script_data['title']}\n\n{script_data['script']}")
    upload_file(local_txt, "scripts")

    return script_data, fid


# ── Test block ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    today           = datetime.date.today().isoformat()
    candidates_path = os.path.join(TMP, f"candidates_{today}.json")

    if not os.path.exists(candidates_path):
        print(f"No candidates file found at {candidates_path}")
        print("Run discover.py first to generate today's candidates")
    else:
        with open(candidates_path, encoding="utf-8") as f:
            data = json.load(f)

        candidates = data["candidates"]
        print(f"Loaded {len(candidates)} candidates from {candidates_path}\n")

        # Change account_type to "history" to test the history branch
        script_data, fid = run_scripting(candidates, account_type="news")

        print(f"\n{'─' * 65}")
        print(f"Title:      {script_data['title']}")
        print(f"Word count: {len(script_data['script'].split())}")
        print(f"Scenes:     {len(script_data.get('scenes', []))}")
        print(f"Drive ID:   {fid}")
        print(f"\n── Script ──────────────────────────────────────────────────\n")
        print(script_data["script"])