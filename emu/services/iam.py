import json

from ..common import F, action as A, scenario as S, service, account_id

U = F("user", "User name", "dev-alice", sync=True)
P = F("policy", "Policy name", "S3ReadOnlyDemo", sync=True)
R = F("role", "Role name", "app-role", sync=True)
POLICY_DOC = json.dumps({"Version": "2012-10-17", "Statement": [
    {"Effect": "Allow", "Action": ["s3:GetObject", "s3:ListBucket"], "Resource": ["arn:aws:s3:::demo-docs-bucket", "arn:aws:s3:::demo-docs-bucket/*"]}]}, indent=2)
TRUST = json.dumps({"Version": "2012-10-17", "Statement": [
    {"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]}, indent=2)


def parn(c, name):
    return f"arn:aws:iam::{account_id(c)}:policy/{name}"


def create_user(c, v):
    return c("iam").create_user(UserName=v["user"], Tags=[{"Key": "team", "Value": v["team"]}])


def list_users(c, v):
    return c("iam").list_users()


def get_user(c, v):
    return c("iam").get_user(UserName=v["user"])


def create_key(c, v):
    return c("iam").create_access_key(UserName=v["user"])


def list_keys(c, v):
    return c("iam").list_access_keys(UserName=v["user"])


def create_policy(c, v):
    return c("iam").create_policy(PolicyName=v["policy"], PolicyDocument=v["doc"], Description=v["desc"])


def list_policies(c, v):
    return c("iam").list_policies(Scope="Local")


def attach(c, v):
    return c("iam").attach_user_policy(UserName=v["user"], PolicyArn=parn(c, v["policy"]))


def list_attached(c, v):
    return c("iam").list_attached_user_policies(UserName=v["user"])


def create_role(c, v):
    return c("iam").create_role(RoleName=v["role"], AssumeRolePolicyDocument=v["trust"], Description="created from console")


def list_roles(c, v):
    return c("iam").list_roles()


def simulate(c, v):
    r = c("iam").simulate_principal_policy(PolicySourceArn=f"arn:aws:iam::{account_id(c)}:user/{v['user']}",
                                           ActionNames=v.lines("actions"), ResourceArns=v.lines("resources"))
    return [{"Action": e["EvalActionName"], "Resource": e.get("EvalResourceName"), "Decision": e["EvalDecision"]} for e in r["EvaluationResults"]]


def create_group(c, v):
    g = c("iam").create_group(GroupName=v["group"])
    c("iam").add_user_to_group(GroupName=v["group"], UserName=v["user"])
    return g


def cascade(c, v):
    i = c("iam")
    out = []
    for p in i.list_attached_user_policies(UserName=v["user"]).get("AttachedPolicies", []):
        i.detach_user_policy(UserName=v["user"], PolicyArn=p["PolicyArn"])
        out.append("detached " + p["PolicyName"])
    for k in i.list_access_keys(UserName=v["user"]).get("AccessKeyMetadata", []):
        i.delete_access_key(UserName=v["user"], AccessKeyId=k["AccessKeyId"])
        out.append("deleted key " + k["AccessKeyId"])
    i.delete_user(UserName=v["user"])
    out.append("deleted user " + v["user"])
    return out


def delete_policy(c, v):
    return c("iam").delete_policy(PolicyArn=parn(c, v["policy"]))


def delete_role(c, v):
    return c("iam").delete_role(RoleName=v["role"])


def whoami(c, v):
    return c("sts").get_caller_identity()


def scn_least(c, v, s):
    i, u, p = c("iam"), v["user"], v["policy"]
    s.run("Who am I? (STS)", lambda: c("sts").get_caller_identity())
    arn = s.run("Create read-only S3 policy", lambda: i.create_policy(PolicyName=p, PolicyDocument=POLICY_DOC)["Policy"]["Arn"])
    s.run("Create user", lambda: i.create_user(UserName=u))
    s.run("Attach policy to user", lambda: i.attach_user_policy(UserName=u, PolicyArn=arn))
    s.run("Create access key", lambda: {k: val for k, val in i.create_access_key(UserName=u)["AccessKey"].items() if k != "SecretAccessKey"})
    s.run("List attached policies", lambda: i.list_attached_user_policies(UserName=u)["AttachedPolicies"])
    s.run("Simulate: GetObject (expect allowed) vs PutObject (expect denied)", lambda: [
        (e["EvalActionName"], e["EvalDecision"]) for e in i.simulate_principal_policy(
            PolicySourceArn=f"arn:aws:iam::{account_id(c)}:user/{u}", ActionNames=["s3:GetObject", "s3:PutObject"],
            ResourceArns=["arn:aws:s3:::demo-docs-bucket/file.txt"])["EvaluationResults"]], soft=True)
    if v.flag("cleanup"):
        s.run("Cleanup user + policy", lambda: [cascade(c, {"user": u}), i.delete_policy(PolicyArn=arn)], soft=True)


SERVICE = service(
    "iam", "IAM (+STS)", "basic", "iam", "Identity: users, access keys, policies, roles, policy simulation; STS caller identity.",
    ("iam", "list_users", {}),
    [
        A("whoami", "STS: who am I", "GetCallerIdentity - the emulator acts as account 000000000000.", [], whoami),
        A("create_user", "Create user", "", [U, F("team", "Tag: team", "platform")], create_user),
        A("list_users", "List users", "", [], list_users),
        A("get_user", "Get user", "", [U], get_user),
        A("create_key", "Create access key", "These keys also work against the emulator.", [U], create_key),
        A("list_keys", "List access keys", "", [U], list_keys),
        A("create_policy", "Create policy", "", [P, F("desc", "Description", "Read-only access to the demo bucket"), F("doc", "Policy document", POLICY_DOC, "textarea", rows=12)], create_policy),
        A("list_policies", "List local policies", "", [], list_policies),
        A("attach", "Attach policy to user", "", [U, P], attach),
        A("list_attached", "List attached policies", "", [U], list_attached),
        A("create_role", "Create role", "", [R, F("trust", "Trust policy", TRUST, "textarea", rows=9)], create_role),
        A("list_roles", "List roles", "", [], list_roles),
        A("simulate", "Simulate policy", "Would the user be allowed to do this?", [U, F("actions", "Actions (one per line)", "s3:GetObject\ns3:PutObject", "textarea", rows=3), F("resources", "Resources (one per line)", "arn:aws:s3:::demo-docs-bucket/report.csv", "textarea", rows=2)], simulate),
        A("create_group", "Create group + add user", "", [U, F("group", "Group", "developers")], create_group),
        A("cascade", "Delete user (cascade)", "Detaches policies, removes keys, deletes the user.", [U], cascade),
        A("delete_policy", "Delete policy", "", [P], delete_policy),
        A("delete_role", "Delete role", "", [R], delete_role),
    ],
    [S("least", "Least-privilege developer user", "Create a read-only S3 policy and a user, attach, mint an access key, then simulate allowed/denied actions.",
       [F("user", "User", "dev-bob"), F("policy", "Policy", "S3ReadOnlyScenario"), F("cleanup", "Clean up afterwards", True, "checkbox")], scn_least)],
    "https://docs.aws.amazon.com/IAM/latest/APIReference/welcome.html")
