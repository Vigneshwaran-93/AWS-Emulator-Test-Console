from ..common import F, action as A, scenario as S, service

G = F("guardrail_id", "Guardrail ID", "", help="Returned by Create guardrail", sync=True)


def list_models(c, v):
    kw = {}
    if v["provider"]:
        kw["byProvider"] = v["provider"]
    if v["output"]:
        kw["byOutputModality"] = v["output"]
    r = c("bedrock").list_foundation_models(**kw)
    return {"count": len(r["modelSummaries"]),
            "models": [{"modelId": m["modelId"], "provider": m.get("providerName"), "in": m.get("inputModalities"), "out": m.get("outputModalities")}
                       for m in r["modelSummaries"]]}


def get_model(c, v):
    return c("bedrock").get_foundation_model(modelIdentifier=v["model"])


def list_profiles(c, v):
    return c("bedrock").list_inference_profiles()


def create_guardrail(c, v):
    return c("bedrock").create_guardrail(
        name=v["name"], description="Created from the emulator console",
        topicPolicyConfig={"topicsConfig": [{"name": v["topic"], "definition": v["topic_def"], "examples": [v["topic_example"]], "type": "DENY"}]},
        wordPolicyConfig={"wordsConfig": [{"text": w} for w in v.lines("words")]},
        blockedInputMessaging=v["blocked_in"], blockedOutputsMessaging=v["blocked_out"])


def list_guardrails(c, v):
    return c("bedrock").list_guardrails()


def get_guardrail(c, v):
    return c("bedrock").get_guardrail(guardrailIdentifier=v["guardrail_id"])


def delete_guardrail(c, v):
    return c("bedrock").delete_guardrail(guardrailIdentifier=v["guardrail_id"])


def list_custom(c, v):
    return c("bedrock").list_custom_models()


def list_jobs(c, v):
    return c("bedrock").list_model_customization_jobs()


def scn_catalog(c, v, s):
    b = c("bedrock")
    ms = s.run("List all foundation models", lambda: b.list_foundation_models()["modelSummaries"], show=False)
    if ms:
        s.note("Providers available", sorted({m.get("providerName") for m in ms}))
        s.note("Text-output models (first 10)", [m["modelId"] for m in ms if "TEXT" in (m.get("outputModalities") or [])][:10])
    s.run("Filter: Anthropic models", lambda: [m["modelId"] for m in b.list_foundation_models(byProvider="Anthropic")["modelSummaries"]], soft=True)
    s.run("Filter: embedding models", lambda: [m["modelId"] for m in b.list_foundation_models(byOutputModality="EMBEDDING")["modelSummaries"]], soft=True)
    s.run(f"Get model details: {v['model']}", lambda: b.get_foundation_model(modelIdentifier=v["model"]), soft=True)
    gid = s.run("Create guardrail (deny 'investment advice', block words)", lambda: b.create_guardrail(
        name=v["gname"], description="Finance assistant safety",
        topicPolicyConfig={"topicsConfig": [{"name": "InvestmentAdvice", "definition": "Recommendations on buying or selling stocks, funds or crypto.", "examples": ["Which stock should I buy?"], "type": "DENY"}]},
        wordPolicyConfig={"wordsConfig": [{"text": "guaranteed returns"}]},
        blockedInputMessaging="I can't help with that request.", blockedOutputsMessaging="I can't share that response."), soft=True)
    if gid:
        gid_ = gid["guardrailId"]
        s.run("List guardrails", lambda: [g["name"] for g in b.list_guardrails()["guardrails"]], soft=True)
        s.run("Get guardrail", lambda: b.get_guardrail(guardrailIdentifier=gid_), soft=True)
        if v.flag("cleanup"):
            s.run("Delete guardrail", lambda: b.delete_guardrail(guardrailIdentifier=gid_), soft=True)


SERVICE = service(
    "bedrock", "Bedrock", "genai", "bedrock", "Control plane for generative AI: foundation-model catalog, guardrails, custom models.",
    ("bedrock", "list_foundation_models", {}),
    [
        A("list_models", "List foundation models", "Filter by provider / output modality.", [F("provider", "Provider", "", "select", ["", "Anthropic", "Amazon", "Meta", "Mistral AI", "Cohere", "AI21 Labs"]),
          F("output", "Output modality", "", "select", ["", "TEXT", "IMAGE", "EMBEDDING"])], list_models),
        A("get_model", "Get foundation model", "", [F("model", "Model ID", "anthropic.claude-haiku-4-5-20251001-v1:0", sync=True)], get_model),
        A("list_profiles", "List inference profiles", "", [], list_profiles),
        A("create_guardrail", "Create guardrail", "Deny a topic and block specific words.", [F("name", "Name", "finance-safety"), F("topic", "Denied topic", "InvestmentAdvice"),
          F("topic_def", "Topic definition", "Recommendations on buying or selling stocks, funds or crypto.", "textarea", rows=2), F("topic_example", "Example phrase", "Which stock should I buy today?"),
          F("words", "Blocked words (one per line)", "guaranteed returns\nrisk-free profit", "textarea", rows=2), F("blocked_in", "Blocked input message", "Sorry, I can't help with that request."),
          F("blocked_out", "Blocked output message", "Sorry, I can't share that response.")], create_guardrail),
        A("list_guardrails", "List guardrails", "", [], list_guardrails),
        A("get_guardrail", "Get guardrail", "", [G], get_guardrail),
        A("delete_guardrail", "Delete guardrail", "", [G], delete_guardrail),
        A("list_custom", "List custom models", "", [], list_custom),
        A("list_jobs", "List customization jobs", "Fine-tuning jobs.", [], list_jobs),
    ],
    [S("catalog", "Model catalog + guardrail setup", "Explore the model catalog by provider/modality, then create, read and remove a guardrail.",
       [F("model", "Model to inspect", "amazon.nova-lite-v1:0"), F("gname", "Guardrail name", "scenario-finance-guardrail"), F("cleanup", "Clean up afterwards", True, "checkbox")], scn_catalog)],
    "https://docs.aws.amazon.com/bedrock/latest/APIReference/welcome.html")
