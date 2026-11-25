import base64
import json

from ..common import F, action as A, scenario as S, service, make_zip, wait_lambda

CODE = '''import json

def lambda_handler(event, context):
    name = event.get("name", "world")
    print("processing event for", name)
    return {
        "statusCode": 200,
        "body": json.dumps({"message": f"Hello, {name}!", "request_id": context.aws_request_id}),
    }
'''
ROLE = "arn:aws:iam::000000000000:role/lambda-demo-role"
N = F("fn", "Function name", "hello-fn", sync=True)
RUNTIMES = ["python3.12", "python3.13", "python3.11", "nodejs20.x", "nodejs22.x"]


def create(c, v):
    ext = "js" if v["runtime"].startswith("node") else "py"
    kw = dict(FunctionName=v["fn"], Runtime=v["runtime"], Role=v["role"], Handler=v["handler"],
              Code={"ZipFile": make_zip(f"lambda_function.{ext}" if ext == "py" else "index.js", v["code"])},
              Timeout=int(v.num("timeout", 10)), MemorySize=int(v.num("memory", 128)), Description=v["description"])
    env = v.json("env", {})
    if env:
        kw["Environment"] = {"Variables": env}
    return c("lambda").create_function(**kw)


def list_fns(c, v):
    return c("lambda").list_functions()


def get_fn(c, v):
    return c("lambda").get_function(FunctionName=v["fn"])


def invoke(c, v):
    r = c("lambda").invoke(FunctionName=v["fn"], InvocationType=v["itype"], LogType="Tail", Payload=v["payload"].encode())
    out = {"StatusCode": r["StatusCode"], "FunctionError": r.get("FunctionError"), "ExecutedVersion": r.get("ExecutedVersion"),
           "Payload": r["Payload"].read().decode("utf-8", "replace")}
    try:
        out["Payload"] = json.loads(out["Payload"])
    except Exception:  # noqa
        pass
    if r.get("LogResult"):
        out["Log"] = base64.b64decode(r["LogResult"]).decode("utf-8", "replace")
    return out


def update_code(c, v):
    return c("lambda").update_function_code(FunctionName=v["fn"], ZipFile=make_zip("lambda_function.py", v["code"]))


def update_cfg(c, v):
    return c("lambda").update_function_configuration(FunctionName=v["fn"], Environment={"Variables": v.json("env", {})},
                                                     Timeout=int(v.num("timeout", 10)), MemorySize=int(v.num("memory", 128)))


def publish(c, v):
    return c("lambda").publish_version(FunctionName=v["fn"], Description=v["description"])


def alias(c, v):
    return c("lambda").create_alias(FunctionName=v["fn"], Name=v["alias"], FunctionVersion=v["version"])


def delete(c, v):
    return c("lambda").delete_function(FunctionName=v["fn"])


def scn_deploy(c, v, s):
    lam, iam, name = c("lambda"), c("iam"), v["fn"]
    trust = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]})
    role = s.run("Create execution role", lambda: iam.create_role(RoleName="lambda-demo-role", AssumeRolePolicyDocument=trust)["Role"]["Arn"], soft=True) or ROLE
    s.run("Create function", lambda: lam.create_function(FunctionName=name, Runtime="python3.12", Role=role, Handler="lambda_function.lambda_handler",
                                                         Code={"ZipFile": make_zip("lambda_function.py", CODE)}, Environment={"Variables": {"STAGE": "dev"}}))
    s.run("Wait for function to become Active", lambda: wait_lambda(c, name))
    for who in v.lines("names"):
        s.run(f"Invoke with name={who}", lambda who=who: json.loads(lam.invoke(FunctionName=name, Payload=json.dumps({"name": who}).encode())["Payload"].read()))
    s.run("Publish version 1", lambda: lam.publish_version(FunctionName=name), soft=True)
    s.run("Create alias 'live' -> $LATEST", lambda: lam.create_alias(FunctionName=name, Name="live", FunctionVersion="$LATEST"), soft=True)
    s.run("List functions", lambda: [f["FunctionName"] for f in lam.list_functions()["Functions"]])
    if v.flag("cleanup"):
        s.run("Delete function", lambda: lam.delete_function(FunctionName=name), soft=True)
        s.run("Delete role", lambda: iam.delete_role(RoleName="lambda-demo-role"), soft=True)


SERVICE = service(
    "lambda", "Lambda", "basic", "lambda", "Serverless functions: deploy a zip, invoke, version, alias.",
    ("lambda", "list_functions", {}),
    [
        A("create", "Create function", "Packages your code into a zip and deploys it.", [N,
          F("runtime", "Runtime", "python3.12", "select", RUNTIMES), F("handler", "Handler", "lambda_function.lambda_handler"),
          F("role", "Role ARN", ROLE), F("timeout", "Timeout (s)", 10, "number"), F("memory", "Memory (MB)", 128, "number"),
          F("description", "Description", "Greeting function"), F("env", "Env vars (JSON)", '{"STAGE": "dev"}', "textarea", rows=2),
          F("code", "Source code", CODE, "textarea", rows=11)], create),
        A("list", "List functions", "", [], list_fns),
        A("get", "Get function", "", [N], get_fn),
        A("invoke", "Invoke", "Runs the function with your JSON event.", [N, F("itype", "Invocation type", "RequestResponse", "select", ["RequestResponse", "Event", "DryRun"]),
          F("payload", "Event (JSON)", '{"name": "Alex"}', "textarea", rows=3)], invoke),
        A("update_code", "Update code", "", [N, F("code", "Source code", CODE, "textarea", rows=8)], update_code),
        A("update_cfg", "Update configuration", "", [N, F("env", "Env vars (JSON)", '{"STAGE": "prod"}', "textarea", rows=2), F("timeout", "Timeout (s)", 15, "number"), F("memory", "Memory (MB)", 256, "number")], update_cfg),
        A("publish", "Publish version", "", [N, F("description", "Description", "release 1")], publish),
        A("alias", "Create alias", "", [N, F("alias", "Alias", "live"), F("version", "Version", "$LATEST")], alias),
        A("delete", "Delete function", "", [N], delete),
    ],
    [S("deploy", "Deploy and invoke", "Create IAM role, deploy a function, invoke it for several names, publish a version and alias.",
       [F("fn", "Function name", "greeter-demo"), F("names", "Invoke for names (one per line)", "Asha\nCarlos\nMei", "textarea", rows=3), F("cleanup", "Clean up afterwards", True, "checkbox")], scn_deploy)],
    "https://docs.aws.amazon.com/lambda/latest/api/welcome.html")
