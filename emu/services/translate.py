from ..common import F, action as A, scenario as S, service

LANGS = ["auto", "en", "es", "fr", "de", "it", "pt", "ja", "ko", "hi", "ar", "zh", "ru", "nl", "ta"]
TXT = "Your order has shipped and will arrive on Friday. Thank you for shopping with us!"
TERM = "en,de\nCloud Pantry,Cloud Speisekammer\nsmart shelf,intelligentes Regal\n"


def translate(c, v):
    kw = dict(Text=v["text"], SourceLanguageCode=v["src"], TargetLanguageCode=v["dst"])
    settings = {}
    if v["formality"]:
        settings["Formality"] = v["formality"]
    if v.flag("profanity"):
        settings["Profanity"] = "MASK"
    if settings:
        kw["Settings"] = settings
    if v["term"]:
        kw["TerminologyNames"] = [v["term"]]
    return c("translate").translate_text(**kw)


def translate_doc(c, v):
    r = c("translate").translate_document(Document={"Content": v["text"].encode(), "ContentType": "text/plain"}, SourceLanguageCode=v["src"], TargetLanguageCode=v["dst"])
    r["TranslatedDocument"] = r["TranslatedDocument"]["Content"]
    return r


def list_langs(c, v):
    r = c("translate").list_languages()
    return {"count": len(r["Languages"]), "languages": [f'{l["LanguageCode"]} - {l["LanguageName"]}' for l in r["Languages"]]}


def import_term(c, v):
    return c("translate").import_terminology(Name=v["term_name"], MergeStrategy="OVERWRITE", TerminologyData={"File": v["csv"].encode(), "Format": "CSV"})


def list_terms(c, v):
    return c("translate").list_terminologies()


def get_term(c, v):
    return c("translate").get_terminology(Name=v["term_name"])


def delete_term(c, v):
    return c("translate").delete_terminology(Name=v["term_name"])


def scn_multi(c, v, s):
    tr = c("translate")
    for code in v.lines("targets"):
        s.run(f"Translate to {code}", lambda code=code: tr.translate_text(Text=v["text"], SourceLanguageCode="en", TargetLanguageCode=code)["TranslatedText"])
    first = (v.lines("targets") or ["es"])[0]
    fwd = s.run(f"Round trip: en -> {first}", lambda: tr.translate_text(Text=v["text"], SourceLanguageCode="en", TargetLanguageCode=first)["TranslatedText"], soft=True)
    if fwd:
        s.run(f"Round trip: {first} -> en", lambda: tr.translate_text(Text=fwd, SourceLanguageCode=first, TargetLanguageCode="en")["TranslatedText"], soft=True)
    s.run("Auto-detect source language", lambda: tr.translate_text(Text="Bonjour, comment puis-je suivre ma commande ?", SourceLanguageCode="auto", TargetLanguageCode="en"), soft=True)
    s.run("Import terminology + translate with it", lambda: (
        tr.import_terminology(Name="brand-terms", MergeStrategy="OVERWRITE", TerminologyData={"File": TERM.encode(), "Format": "CSV"}),
        tr.translate_text(Text="Welcome to Cloud Pantry and your new smart shelf.", SourceLanguageCode="en", TargetLanguageCode="de", TerminologyNames=["brand-terms"])["TranslatedText"]), soft=True)
    s.run("Supported languages", lambda: len(tr.list_languages()["Languages"]), soft=True)


SERVICE = service(
    "translate", "Translate", "genai", "translate", "Neural machine translation: text, documents, custom terminology.",
    ("translate", "list_terminologies", {}),
    [
        A("translate", "Translate text", "", [F("text", "Text", TXT, "textarea", rows=3), F("src", "Source", "en", "select", LANGS), F("dst", "Target", "es", "select", LANGS[1:]),
          F("formality", "Formality", "", "select", ["", "FORMAL", "INFORMAL"]), F("profanity", "Mask profanity", False, "checkbox"), F("term", "Terminology name (optional)", "")], translate),
        A("translate_doc", "Translate document", "Plain-text document.", [F("text", "Document", TXT, "textarea", rows=3), F("src", "Source", "en", "select", LANGS), F("dst", "Target", "fr", "select", LANGS[1:])], translate_doc),
        A("list_langs", "List languages", "", [], list_langs),
        A("import_term", "Import terminology", "CSV with a header row of language codes.", [F("term_name", "Name", "brand-terms", sync=True), F("csv", "CSV", TERM, "textarea", rows=4)], import_term),
        A("list_terms", "List terminologies", "", [], list_terms),
        A("get_term", "Get terminology", "", [F("term_name", "Name", "brand-terms", sync=True)], get_term),
        A("delete_term", "Delete terminology", "", [F("term_name", "Name", "brand-terms", sync=True)], delete_term),
    ],
    [S("multi", "Multilingual support message", "Translate one message into several languages, round-trip it, auto-detect a source language and use custom terminology.",
       [F("text", "English message", TXT, "textarea", rows=3), F("targets", "Target languages (one per line)", "es\nfr\nde\nja\nhi", "textarea", rows=5)], scn_multi)],
    "https://docs.aws.amazon.com/translate/latest/APIReference/Welcome.html")
