import base64

from ..common import F, action as A, scenario as S, service

TXT = "Hello and welcome to the Cloud Pantry help line. Your order has shipped and will arrive on Friday."
VOICES = ["Joanna", "Matthew", "Ruth", "Stephen", "Amy", "Brian", "Aditi", "Kajal", "Lupe", "Mizuki", "Celine", "Hans"]
LEX = '''<?xml version="1.0" encoding="UTF-8"?>
<lexicon version="1.0" xmlns="http://www.w3.org/2005/01/pronunciation-lexicon" alphabet="ipa" xml:lang="en-US">
  <lexeme><grapheme>AWS</grapheme><alias>Amazon Web Services</alias></lexeme>
  <lexeme><grapheme>SQS</grapheme><alias>simple queue service</alias></lexeme>
</lexicon>'''


def _synth(c, v):
    kw = dict(Text=v["text"], VoiceId=v["voice"], OutputFormat=v["fmt"], TextType=v["ttype"], Engine=v["engine"])
    if v.get("lexicon"):
        kw["LexiconNames"] = [v["lexicon"]]
    return c("polly").synthesize_speech(**kw)


def synth(c, v):
    r = _synth(c, v)
    data = r["AudioStream"].read()
    mime = {"mp3": "audio/mpeg", "ogg_vorbis": "audio/ogg", "pcm": "audio/L16"}[v["fmt"]]
    return {"ContentType": r.get("ContentType"), "RequestCharacters": r.get("RequestCharacters"), "audio_bytes": len(data),
            "_audio": {"mime": mime, "b64": base64.b64encode(data).decode()} if v["fmt"] != "pcm" else None}


def voices(c, v):
    kw = {"Engine": v["engine"]} if v["engine"] else {}
    if v["lang"]:
        kw["LanguageCode"] = v["lang"]
    r = c("polly").describe_voices(**kw)
    return {"count": len(r["Voices"]), "voices": [f'{x["Id"]} ({x["LanguageCode"]}, {x["Gender"]})' for x in r["Voices"]]}


def put_lex(c, v):
    return c("polly").put_lexicon(Name=v["lname"], Content=v["content"])


def list_lex(c, v):
    return c("polly").list_lexicons()


def get_lex(c, v):
    return c("polly").get_lexicon(Name=v["lname"])


def del_lex(c, v):
    return c("polly").delete_lexicon(Name=v["lname"])


def task(c, v):
    return c("polly").start_speech_synthesis_task(Text=v["text"], VoiceId=v["voice"], OutputFormat="mp3", OutputS3BucketName=v["bucket"], Engine=v["engine"])


def get_task(c, v):
    return c("polly").get_speech_synthesis_task(TaskId=v["task_id"])


def scn_announce(c, v, s):
    p = c("polly")
    s.run("Put pronunciation lexicon", lambda: p.put_lexicon(Name="techterms", Content=LEX), soft=True)
    s.run("List English voices", lambda: [x["Id"] for x in p.describe_voices(LanguageCode="en-US")["Voices"]][:10])
    first_audio = None
    for voice in v.lines("voices"):
        def go(voice=voice):
            r = p.synthesize_speech(Text=v["text"], VoiceId=voice, OutputFormat="mp3", Engine=v["engine"], LexiconNames=["techterms"])
            data = r["AudioStream"].read()
            return {"voice": voice, "bytes": len(data), "ContentType": r.get("ContentType")}
        s.run(f"Synthesize with {voice}", go, soft=True)
    s.run("SSML with pause and emphasis", lambda: len(p.synthesize_speech(
        Text='<speak>Your code is <say-as interpret-as="digits">482913</say-as>. <break time="500ms"/> <emphasis>Do not share it.</emphasis></speak>',
        TextType="ssml", VoiceId="Joanna", OutputFormat="mp3", Engine=v["engine"])["AudioStream"].read()), soft=True)
    if v.flag("cleanup"):
        s.run("Delete lexicon", lambda: p.delete_lexicon(Name="techterms"), soft=True)


SERVICE = service(
    "polly", "Polly", "genai", "polly", "Text-to-speech with voices, SSML, lexicons and async synthesis tasks. Audio plays right in the result.",
    ("polly", "describe_voices", {}),
    [
        A("synth", "Synthesize speech", "Result includes an audio player if the emulator returns audio.", [F("text", "Text / SSML", TXT, "textarea", rows=3), F("voice", "Voice", "Joanna", "select", VOICES),
          F("engine", "Engine", "neural", "select", ["neural", "standard", "generative", "long-form"]), F("fmt", "Format", "mp3", "select", ["mp3", "ogg_vorbis", "pcm"]),
          F("ttype", "Text type", "text", "select", ["text", "ssml"]), F("lexicon", "Lexicon (optional)", "")], synth),
        A("voices", "Describe voices", "", [F("lang", "Language code", "en-US", "select", ["", "en-US", "en-GB", "en-IN", "es-ES", "fr-FR", "de-DE", "ja-JP", "hi-IN"]), F("engine", "Engine", "", "select", ["", "neural", "standard"])], voices),
        A("put_lex", "Put lexicon", "PLS XML pronunciation rules.", [F("lname", "Name", "techterms", sync=True), F("content", "Lexicon (PLS XML)", LEX, "textarea", rows=8)], put_lex),
        A("list_lex", "List lexicons", "", [], list_lex),
        A("get_lex", "Get lexicon", "", [F("lname", "Name", "techterms", sync=True)], get_lex),
        A("del_lex", "Delete lexicon", "", [F("lname", "Name", "techterms", sync=True)], del_lex),
        A("task", "Start async synthesis task", "Writes audio to an S3 bucket (create it on the S3 page first).", [F("text", "Text", TXT, "textarea", rows=2), F("voice", "Voice", "Matthew", "select", VOICES),
          F("engine", "Engine", "neural", "select", ["neural", "standard"]), F("bucket", "Output bucket", "demo-docs-bucket")], task),
        A("get_task", "Get synthesis task", "", [F("task_id", "Task ID", "")], get_task),
    ],
    [S("announce", "Voice announcement set", "Create a pronunciation lexicon and synthesize one announcement in several voices, plus an SSML sample.",
       [F("text", "Announcement", "Attention please: the AWS SQS maintenance window begins at nine PM tonight.", "textarea", rows=2), F("voices", "Voices (one per line)", "Joanna\nMatthew\nKajal", "textarea", rows=3),
        F("engine", "Engine", "neural", "select", ["neural", "standard"]), F("cleanup", "Clean up afterwards", True, "checkbox")], scn_announce)],
    "https://docs.aws.amazon.com/polly/latest/dg/API_Reference.html")
