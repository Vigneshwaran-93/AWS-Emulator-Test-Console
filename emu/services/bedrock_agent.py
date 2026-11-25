import uuid

from ..common import F, action as A, scenario as S, service

AID = F("agent_id", "Agent ID", "", sync=True, help="From Create agent")
ALIAS = F("alias_id", "Agent alias ID", "TSTALIASID", sync=True, help="TSTALIASID is the built-in test alias")
ROLE = "arn:aws:iam::000000000000:role/bedrock-agent-role"
INSTR = "You are a helpful retail assistant. Answer questions about orders, shipping and returns politely and concisely."


def create_agent(c, v):
    return c("bedrock-agent").create_agent(agentName=v["name"], agentResourceRoleArn=v["role"], foundationModel=v["model"], instruction=v["instruction"],
                                           idleSessionTTLInSeconds=int(v.num("ttl", 600)))


def list_agents(c, v):
    return c("bedrock-agent").list_agents()


def get_agent(c, v):
    return c("bedrock-agent").get_agent(agentId=v["agent_id"])


def prepare(c, v):
    return c("bedrock-agent").prepare_agent(agentId=v["agent_id"])


def create_alias(c, v):
    return c("bedrock-agent").create_agent_alias(agentId=v["agent_id"], agentAliasName=v["alias_name"])


def list_aliases(c, v):
    return c("bedrock-agent").list_agent_aliases(agentId=v["agent_id"])


def list_kbs(c, v):
    return c("bedrock-agent").list_knowledge_bases()


def delete_agent(c, v):
    return c("bedrock-agent").delete_agent(agentId=v["agent_id"], skipResourceInUseCheck=True)


def invoke_agent(c, v):
    r = c("bedrock-agent-runtime").invoke_agent(agentId=v["agent_id"], agentAliasId=v["alias_id"], sessionId=v["session"] or str(uuid.uuid4()), inputText=v["text"])
    text, events = "", 0
    for ev in r["completion"]:
        events += 1
        if "chunk" in ev:
            text += ev["chunk"]["bytes"].decode("utf-8", "replace")
    return {"sessionId": r.get("sessionId"), "completion": text, "events": events}


def retrieve(c, v):
    return c("bedrock-agent-runtime").retrieve(knowledgeBaseId=v["kb_id"], retrievalQuery={"text": v["query"]})


def scn_agent(c, v, s):
    ba, rt = c("bedrock-agent"), c("bedrock-agent-runtime")
    ag = s.run("Create agent", lambda: ba.create_agent(agentName=v["name"], agentResourceRoleArn=ROLE, foundationModel=v["model"], instruction=INSTR))
    aid = ag["agent"]["agentId"]
    s.run("Prepare agent", lambda: ba.prepare_agent(agentId=aid), soft=True)
    al = s.run("Create alias 'live'", lambda: ba.create_agent_alias(agentId=aid, agentAliasName="live"), soft=True)
    alias_id = al["agentAlias"]["agentAliasId"] if al else "TSTALIASID"

    def ask():
        r = rt.invoke_agent(agentId=aid, agentAliasId=alias_id, sessionId=str(uuid.uuid4()), inputText=v["question"])
        return "".join(e["chunk"]["bytes"].decode("utf-8", "replace") for e in r["completion"] if "chunk" in e)
    s.run("Ask the agent a question", ask, soft=True)
    s.run("List agents", lambda: [a["agentName"] for a in ba.list_agents()["agentSummaries"]], soft=True)
    if v.flag("cleanup"):
        s.run("Delete agent", lambda: ba.delete_agent(agentId=aid, skipResourceInUseCheck=True), soft=True)


SERVICE = service(
    "bedrock-agent", "Bedrock Agents", "genai", "bedrock-agent", "Build and run agents and knowledge-base retrieval (bedrock-agent + bedrock-agent-runtime).",
    ("bedrock-agent", "list_agents", {}),
    [
        A("create_agent", "Create agent", "", [F("name", "Agent name", "retail-assistant"), F("model", "Foundation model", "anthropic.claude-haiku-4-5-20251001-v1:0"), F("role", "Role ARN", ROLE),
          F("instruction", "Instruction", INSTR, "textarea", rows=3), F("ttl", "Idle session TTL (s)", 600, "number")], create_agent),
        A("list_agents", "List agents", "", [], list_agents),
        A("get_agent", "Get agent", "", [AID], get_agent),
        A("prepare", "Prepare agent", "Builds DRAFT so it can be invoked.", [AID], prepare),
        A("create_alias", "Create alias", "", [AID, F("alias_name", "Alias name", "live")], create_alias),
        A("list_aliases", "List aliases", "", [AID], list_aliases),
        A("invoke_agent", "Invoke agent", "bedrock-agent-runtime InvokeAgent - assembles the streamed completion.", [AID, ALIAS, F("session", "Session ID (blank = new)", ""),
          F("text", "Your message", "What is your return policy for opened items?", "textarea", rows=2)], invoke_agent),
        A("list_kbs", "List knowledge bases", "", [], list_kbs),
        A("retrieve", "Retrieve from knowledge base", "bedrock-agent-runtime Retrieve.", [F("kb_id", "Knowledge base ID", ""), F("query", "Query", "refund policy for digital goods")], retrieve),
        A("delete_agent", "Delete agent", "", [AID], delete_agent),
    ],
    [S("agent", "Agent lifecycle", "Create an agent, prepare it, add an alias, ask it a question and clean up.",
       [F("name", "Agent name", "scenario-agent"), F("model", "Foundation model", "anthropic.claude-haiku-4-5-20251001-v1:0"), F("question", "Question", "Where can I see my past orders?"), F("cleanup", "Clean up afterwards", True, "checkbox")], scn_agent)],
    "https://docs.aws.amazon.com/bedrock/latest/APIReference/API_Operations_Agents_for_Amazon_Bedrock.html")
