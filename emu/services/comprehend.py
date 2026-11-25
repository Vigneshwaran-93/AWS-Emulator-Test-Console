from ..common import F, action as A, scenario as S, service

REVIEW = ("I ordered the Contoso X200 laptop on 12 November from your Seattle store. Delivery was fast and the screen is gorgeous, "
          "but the battery barely lasts four hours. Please call me at +1 206 555 0142 or email jane.doe@example.com about a replacement.")
T = F("text", "Text", REVIEW, "textarea", rows=5, sync=True)
L = F("lang", "Language", "en", "select", ["en", "es", "fr", "de", "it", "pt", "ja", "ko", "hi", "ar", "zh"])


def dominant(c, v):
    return c("comprehend").detect_dominant_language(Text=v["text"])


def sentiment(c, v):
    return c("comprehend").detect_sentiment(Text=v["text"], LanguageCode=v["lang"])


def entities(c, v):
    return c("comprehend").detect_entities(Text=v["text"], LanguageCode=v["lang"])


def phrases(c, v):
    return c("comprehend").detect_key_phrases(Text=v["text"], LanguageCode=v["lang"])


def pii(c, v):
    return c("comprehend").detect_pii_entities(Text=v["text"], LanguageCode=v["lang"])


def contains_pii(c, v):
    return c("comprehend").contains_pii_entities(Text=v["text"], LanguageCode=v["lang"])


def syntax(c, v):
    return c("comprehend").detect_syntax(Text=v["text"], LanguageCode=v["lang"])


def targeted(c, v):
    return c("comprehend").detect_targeted_sentiment(Text=v["text"], LanguageCode=v["lang"])


def toxic(c, v):
    return c("comprehend").detect_toxic_content(TextSegments=[{"Text": t} for t in v.lines("texts")], LanguageCode=v["lang"])


def batch_sent(c, v):
    return c("comprehend").batch_detect_sentiment(TextList=v.lines("texts"), LanguageCode=v["lang"])


def scn_reviews(c, v, s):
    cp, summary = c("comprehend"), []
    for i, rev in enumerate(v.lines("reviews"), 1):
        sent = s.run(f"Review {i}: sentiment", lambda rev=rev: cp.detect_sentiment(Text=rev, LanguageCode="en"))
        ents = s.run(f"Review {i}: entities", lambda rev=rev: [(e["Type"], e["Text"]) for e in cp.detect_entities(Text=rev, LanguageCode="en")["Entities"]], soft=True)
        s.run(f"Review {i}: key phrases", lambda rev=rev: [k["Text"] for k in cp.detect_key_phrases(Text=rev, LanguageCode="en")["KeyPhrases"]], soft=True)
        s.run(f"Review {i}: PII", lambda rev=rev: [(p["Type"], rev[p["BeginOffset"]:p["EndOffset"]]) for p in cp.detect_pii_entities(Text=rev, LanguageCode="en")["Entities"]], soft=True)
        summary.append({"review": i, "sentiment": sent["Sentiment"] if sent else None})
    s.note("Sentiment summary", summary)
    s.run("Batch sentiment (single call)", lambda: [r["Sentiment"] for r in cp.batch_detect_sentiment(TextList=v.lines("reviews"), LanguageCode="en")["ResultList"]], soft=True)


SERVICE = service(
    "comprehend", "Comprehend", "genai", "comprehend", "NLP: sentiment, entities, key phrases, language, PII and toxicity detection.",
    ("comprehend", "detect_dominant_language", {"Text": "hello world"}),
    [
        A("dominant", "Dominant language", "", [T], dominant),
        A("sentiment", "Sentiment", "", [T, L], sentiment),
        A("entities", "Entities", "People, places, organizations, dates...", [T, L], entities),
        A("phrases", "Key phrases", "", [T, L], phrases),
        A("pii", "PII detection", "", [T, L], pii),
        A("contains_pii", "Contains PII?", "Quick yes/no per PII type.", [T, L], contains_pii),
        A("syntax", "Syntax (parts of speech)", "", [F("text", "Text", "The quick brown fox jumps over the lazy dog.", "textarea", rows=2), L], syntax),
        A("targeted", "Targeted sentiment", "Sentiment per entity.", [T, L], targeted),
        A("toxic", "Toxic content", "One segment per line.", [F("texts", "Segments", "You are a wonderful person.\nI will find you and make you regret this.", "textarea", rows=3), L], toxic),
        A("batch_sent", "Batch sentiment", "One document per line.", [F("texts", "Documents", "Love this phone!\nThe app keeps crashing.\nIt is okay, nothing special.", "textarea", rows=4), L], batch_sent),
    ],
    [S("reviews", "Customer review analysis", "For each review: sentiment, entities, key phrases and PII; then a batch call and a sentiment summary.",
       [F("reviews", "Reviews (one per line)", "The checkout was smooth and the support team in Dublin solved my issue in minutes. Fantastic!\nMy package from Amazon arrived broken and nobody answers at 1-800-555-0199. Terrible service.\nPrice is fair, delivery took the usual 3 days. Email me at sam@example.org for the invoice.", "textarea", rows=6)], scn_reviews)],
    "https://docs.aws.amazon.com/comprehend/latest/APIReference/Welcome.html")
