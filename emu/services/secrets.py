import json

from ..common import F, action as A, scenario as S, service

N = F("name", "Secret name", "prod/orders-db/credentials", sync=True)
VAL = json.dumps({"username": "orders_app", "password": "S3cr3t-Pa55!", "host": "db.internal", "port": 5432, "dbname": "orders"}, indent=2)


def create(c, v):
    return c("secretsmanager").create_secret(Name=v["name"], SecretString=v["value"], Description=v["desc"],
                                             Tags=[{"Key": "env", "Value": v["env"]}])


def get(c, v):
    r = c("secretsmanager").get_secret_value(SecretId=v["name"], **({"VersionStage": v["stage"]} if v["stage"] else {}))
    out = {k: r.get(k) for k in ("Name", "ARN", "VersionId", "VersionStages", "CreatedDate")}
    try:
        out["SecretString"] = json.loads(r["SecretString"])
    except Exception:  # noqa
        out["SecretString"] = r.get("SecretString")
    return out


def list_secrets(c, v):
    return c("secretsmanager").list_secrets()


def describe(c, v):
    return c("secretsmanager").describe_secret(SecretId=v["name"])


def put_value(c, v):
    return c("secretsmanager").put_secret_value(SecretId=v["name"], SecretString=v["value"])


def update(c, v):
    return c("secretsmanager").update_secret(SecretId=v["name"], Description=v["desc"])


def versions(c, v):
    return c("secretsmanager").list_secret_version_ids(SecretId=v["name"], IncludeDeprecated=True)


def rand(c, v):
    return c("secretsmanager").get_random_password(PasswordLength=int(v.num("length", 24)), ExcludePunctuation=v.flag("nopunct"))


def delete(c, v):
    kw = {"ForceDeleteWithoutRecovery": True} if v.flag("force") else {"RecoveryWindowInDays": 7}
    return c("secretsmanager").delete_secret(SecretId=v["name"], **kw)


def scn_rotate(c, v, s):
    sm, n = c("secretsmanager"), v["name"]
    pw = s.run("Generate random password", lambda: sm.get_random_password(PasswordLength=24, ExcludePunctuation=True)["RandomPassword"])
    s.run("Create secret", lambda: sm.create_secret(Name=n, SecretString=json.dumps({"username": "svc_reports", "password": "initial-password"}), Description="Reporting DB login"))
    s.run("Read current value", lambda: json.loads(sm.get_secret_value(SecretId=n)["SecretString"]))
    s.run("Rotate: put new version", lambda: sm.put_secret_value(SecretId=n, SecretString=json.dumps({"username": "svc_reports", "password": pw or "rotated-pw"})))
    s.run("Read AWSCURRENT", lambda: json.loads(sm.get_secret_value(SecretId=n, VersionStage="AWSCURRENT")["SecretString"]))
    s.run("Read AWSPREVIOUS", lambda: json.loads(sm.get_secret_value(SecretId=n, VersionStage="AWSPREVIOUS")["SecretString"]), soft=True)
    s.run("List versions", lambda: sm.list_secret_version_ids(SecretId=n, IncludeDeprecated=True)["Versions"], soft=True)
    if v.flag("cleanup"):
        s.run("Delete secret (force)", lambda: sm.delete_secret(SecretId=n, ForceDeleteWithoutRecovery=True), soft=True)


SERVICE = service(
    "secretsmanager", "Secrets Manager", "basic", "secretsmanager", "Store and rotate credentials with versioning stages.",
    ("secretsmanager", "list_secrets", {}),
    [
        A("create", "Create secret", "", [N, F("desc", "Description", "Orders database login"), F("env", "Tag: env", "prod"), F("value", "Secret value", VAL, "textarea", rows=8)], create),
        A("get", "Get secret value", "", [N, F("stage", "Version stage (optional)", "", "select", ["", "AWSCURRENT", "AWSPREVIOUS"])], get),
        A("list", "List secrets", "", [], list_secrets),
        A("describe", "Describe secret", "", [N], describe),
        A("put_value", "Put new version (rotate)", "", [N, F("value", "New value", VAL.replace("S3cr3t-Pa55!", "N3w-Pa55!2026"), "textarea", rows=8)], put_value),
        A("update", "Update description", "", [N, F("desc", "Description", "Rotated 2026-11")], update),
        A("versions", "List versions", "", [N], versions),
        A("rand", "Random password", "", [F("length", "Length", 24, "number"), F("nopunct", "Exclude punctuation", False, "checkbox")], rand),
        A("delete", "Delete secret", "", [N, F("force", "Force (no recovery window)", True, "checkbox")], delete),
    ],
    [S("rotate", "Credential rotation", "Generate a password, create a secret, rotate it and read current/previous versions.",
       [F("name", "Secret name", "scenario/reports-db"), F("cleanup", "Clean up afterwards", True, "checkbox")], scn_rotate)],
    "https://docs.aws.amazon.com/secretsmanager/latest/apireference/Welcome.html")
