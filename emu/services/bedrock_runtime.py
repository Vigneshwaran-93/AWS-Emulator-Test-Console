import json
import math

from ..common import F, action as A, scenario as S, service

MODEL = F("model", "Model ID", "anthropic.claude-haiku-4-5-20251001-v1:0", sync=True,
          help="e.g. anthropic.claude-haiku-4-5-20251001-v1:0, amazon.nova-lite-v1:0, meta.llama3-8b-instruct-v1:0")
EMBED = "amazon.titan-embed-text-v2:0"
TITAN_BODY = json.dumps({"messages": [{"role": "user", "content": [{"text": "Explain what an SQS dead-letter queue is in two sentences."}]}],
                         "inferenceConfig": {"maxTokens": 256, "temperature": 0.3, "topP": 0.9}}, indent=2)


def _msgs(prompt):
    return [{"role": "user", "content": [{"text": prompt}]}]


def _text(resp):
    try:
        return "".join(b.get("text", "") for b in resp["output"]["message"]["content"])
    except Exception:  # noqa
        return None


def converse(c, v):
    kw = dict(modelId=v["model"], messages=_msgs(v["prompt"]),
              inferenceConfig={"maxTokens": int(v.num("max_tokens", 512)), "temperature": float(v.num("temperature", 0.5))})
    if v["system"]:
        kw["system"] = [{"text": v["system"]}]
    r = c("bedrock-runtime").converse(**kw)
    return {"text": _text(r), "stopReason": r.get("stopReason"), "usage": r.get("usage"), "metrics": r.get("metrics")}


def converse_stream(c, v):
    r = c("bedrock-runtime").converse_stream(modelId=v["model"], messages=_msgs(v["prompt"]),
                                             inferenceConfig={"maxTokens": int(v.num("max_tokens", 512))})
    text, events, usage, stop = "", 0, None, None
    for ev in r["stream"]:
        events += 1
        if "contentBlockDelta" in ev:
            text += ev["contentBlockDelta"]["delta"].get("text", "")
        if "messageStop" in ev:
            stop = ev["messageStop"].get("stopReason")
        if "metadata" in ev:
            usage = ev["metadata"].get("usage")
    return {"text": text, "stream_events": events, "stopReason": stop, "usage": usage}


def invoke(c, v):
    r = c("bedrock-runtime").invoke_model(modelId=v["model"], body=v["body"].encode(), contentType="application/json", accept="application/json")
    raw = r["body"].read().decode("utf-8", "replace")
    try:
        raw = json.loads(raw)
    except Exception:  # noqa
        pass
    return {"contentType": r.get("contentType"), "body": raw}


def embed(c, v):
    r = c("bedrock-runtime").invoke_model(modelId=v["model"], body=json.dumps({"inputText": v["text"]}).encode(), contentType="application/json", accept="application/json")
    d = json.loads(r["body"].read())
    emb = d.get("embedding", [])
    return {"dimensions": len(emb), "first_8": emb[:8], "inputTextTokenCount": d.get("inputTextTokenCount")}


def apply_guardrail(c, v):
    r = c("bedrock-runtime").apply_guardrail(guardrailIdentifier=v["guardrail_id"], guardrailVersion=v["version"], source=v["source"],
                                             content=[{"text": {"text": v["text"]}}])
    return r


def tool_use(c, v):
    tools = {"tools": [{"toolSpec": {"name": "get_order_status", "description": "Look up the shipping status of an order by id.",
                                     "inputSchema": {"json": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]}}}}]}
    msgs = _msgs(v["prompt"])
    brt = c("bedrock-runtime")
    r = brt.converse(modelId=v["model"], messages=msgs, toolConfig=tools)
    out = {"stopReason": r.get("stopReason"), "text": _text(r), "tool_calls": []}
    for b in r["output"]["message"]["content"]:
        if "toolUse" in b:
            out["tool_calls"].append(b["toolUse"])
    return out


def cosine(a, b):
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


def scn_support(c, v, s):
    brt = c("bedrock-runtime")
    ticket = v["ticket"]
    cls = s.run("Classify the ticket", lambda: _text(brt.converse(
        modelId=v["model"], system=[{"text": "Classify the support ticket as one of: billing, technical, account, other. Reply with one word."}],
        messages=_msgs(ticket), inferenceConfig={"maxTokens": 20, "temperature": 0})))
    draft = s.run("Draft a reply", lambda: _text(brt.converse(
        modelId=v["model"], system=[{"text": f"You are a friendly support agent. The ticket category is: {cls}. Write a short, empathetic reply."}],
        messages=_msgs(ticket), inferenceConfig={"maxTokens": 300, "temperature": 0.4})))

    def sim():
        def emb(t):
            return json.loads(brt.invoke_model(modelId=EMBED, body=json.dumps({"inputText": t}).encode(), contentType="application/json", accept="application/json")["body"].read())["embedding"]
        return {"cosine_similarity": round(cosine(emb(ticket), emb(v["kb"])), 4), "dimensions": len(emb(ticket))}
    s.run("Match ticket to knowledge-base article (Titan embeddings)", sim, soft=True)
    s.run("Stream a shorter summary (ConverseStream)", lambda: converse_stream(c, type(v)(model=v["model"], prompt="Summarize in one line: " + ticket, max_tokens=80)), soft=True)
    if v["guardrail_id"]:
        s.run("Check draft with guardrail", lambda: brt.apply_guardrail(guardrailIdentifier=v["guardrail_id"], guardrailVersion="DRAFT", source="OUTPUT",
                                                                        content=[{"text": {"text": draft or ""}}]), soft=True)


def scn_tools(c, v, s):
    brt = c("bedrock-runtime")
    tools = {"tools": [{"toolSpec": {"name": "get_order_status", "description": "Look up shipping status by order id.",
                                     "inputSchema": {"json": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]}}}}]}
    msgs = _msgs(v["prompt"])
    for turn in range(1, 4):
        r = s.run(f"Model turn {turn}", lambda: brt.converse(modelId=v["model"], messages=msgs, toolConfig=tools))
        msg = r["output"]["message"]
        msgs.append(msg)
        calls = [b["toolUse"] for b in msg["content"] if "toolUse" in b]
        if not calls:
            s.note("Final answer", _text(r))
            return
        results = []
        for call in calls:
            data = {"order_id": call["input"].get("order_id"), "status": "SHIPPED", "carrier": "UPS", "eta": "2026-11-28"}
            s.note(f"Local tool executed: {call['name']}", data)
            results.append({"toolResult": {"toolUseId": call["toolUseId"], "content": [{"json": data}]}})
        msgs.append({"role": "user", "content": results})
    s.note("Stopped", "reached 3 turns")


SERVICE = service(
    "bedrock-runtime", "Bedrock Runtime", "genai", "bedrock-runtime", "Invoke models: Converse, streaming, InvokeModel, embeddings, guardrails, tool use.",
    ("bedrock-runtime", "converse", {"modelId": "amazon.nova-lite-v1:0", "messages": [{"role": "user", "content": [{"text": "ping"}]}]}),
    [
        A("converse", "Converse", "Model-agnostic chat API.", [MODEL, F("system", "System prompt", "You are a concise cloud-architecture assistant.", "textarea", rows=2),
          F("prompt", "Your message", "When should I choose SQS over SNS for decoupling microservices?", "textarea", rows=3),
          F("max_tokens", "Max tokens", 512, "number"), F("temperature", "Temperature", 0.5, "number")], converse),
        A("converse_stream", "ConverseStream", "Streams tokens; the console reassembles them.", [MODEL, F("prompt", "Your message", "Write a haiku about queues.", "textarea", rows=2), F("max_tokens", "Max tokens", 200, "number")], converse_stream),
        A("invoke", "InvokeModel (raw body)", "Provider-specific JSON body. Default is the Amazon Nova format.", [F("model", "Model ID", "amazon.nova-lite-v1:0"), F("body", "Request body", TITAN_BODY, "textarea", rows=8)], invoke),
        A("embed", "Embeddings", "Titan Text Embeddings.", [F("model", "Model ID", EMBED), F("text", "Text", "Refund requests are processed within 5 business days.", "textarea", rows=2)], embed),
        A("tool_use", "Converse with tool", "Declares a get_order_status tool and shows whether the model asks to call it.", [MODEL, F("prompt", "Your message", "Where is my order O-2026-0001?", "textarea", rows=2)], tool_use),
        A("apply_guardrail", "ApplyGuardrail", "Evaluate text against a guardrail (create one on the Bedrock page).", [F("guardrail_id", "Guardrail ID", "", sync=True), F("version", "Version", "DRAFT"),
          F("source", "Source", "INPUT", "select", ["INPUT", "OUTPUT"]), F("text", "Text", "Which stock should I buy for guaranteed returns?", "textarea", rows=2)], apply_guardrail),
    ],
    [S("support", "Support-ticket assistant", "Classify a ticket, draft a reply, compute embedding similarity against a KB article, stream a summary and optionally run a guardrail.",
       [MODEL, F("ticket", "Customer ticket", "Hi, I was charged twice for my November subscription and the second charge hasn't been refunded after a week. Order #88213. Please fix this.", "textarea", rows=3),
        F("kb", "Knowledge-base article", "Duplicate charges are refunded to the original payment method within 5-7 business days after verification.", "textarea", rows=2),
        F("guardrail_id", "Guardrail ID (optional)", "")], scn_support),
     S("tools", "Tool-use loop", "Model requests a local function call, the console executes it and returns the result (up to 3 turns).",
       [MODEL, F("prompt", "Your message", "Check the status of order O-2026-0001 and tell me when it arrives.", "textarea", rows=2)], scn_tools)],
    "https://docs.aws.amazon.com/bedrock/latest/APIReference/API_Operations_Amazon_Bedrock_Runtime.html")
