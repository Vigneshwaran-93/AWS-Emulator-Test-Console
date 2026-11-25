from ..common import F, action as A, scenario as S, service

ROLE = "arn:aws:iam::000000000000:role/sagemaker-demo-role"
IMAGE = "683313688378.dkr.ecr.us-east-1.amazonaws.com/sagemaker-scikit-learn:1.2-1-cpu-py3"
M = F("model", "Model name", "churn-model-v1", sync=True)
CFG = F("config", "Endpoint config", "churn-endpoint-config", sync=True)
EP = F("endpoint", "Endpoint name", "churn-endpoint", sync=True)


def create_model(c, v):
    return c("sagemaker").create_model(ModelName=v["model"], ExecutionRoleArn=v["role"],
                                       PrimaryContainer={"Image": v["image"], "ModelDataUrl": v["data"], "Environment": {"SAGEMAKER_PROGRAM": "inference.py"}})


def list_models(c, v):
    return c("sagemaker").list_models()


def describe_model(c, v):
    return c("sagemaker").describe_model(ModelName=v["model"])


def delete_model(c, v):
    return c("sagemaker").delete_model(ModelName=v["model"])


def create_config(c, v):
    return c("sagemaker").create_endpoint_config(EndpointConfigName=v["config"], ProductionVariants=[
        {"VariantName": "AllTraffic", "ModelName": v["model"], "InstanceType": v["itype"], "InitialInstanceCount": int(v.num("count", 1))}])


def create_endpoint(c, v):
    return c("sagemaker").create_endpoint(EndpointName=v["endpoint"], EndpointConfigName=v["config"])


def describe_endpoint(c, v):
    return c("sagemaker").describe_endpoint(EndpointName=v["endpoint"])


def list_endpoints(c, v):
    return c("sagemaker").list_endpoints()


def invoke(c, v):
    r = c("sagemaker-runtime").invoke_endpoint(EndpointName=v["endpoint"], ContentType=v["ctype"], Body=v["body"].encode())
    return {"ContentType": r.get("ContentType"), "Body": r["Body"].read().decode("utf-8", "replace")}


def delete_endpoint(c, v):
    return c("sagemaker").delete_endpoint(EndpointName=v["endpoint"])


def delete_config(c, v):
    return c("sagemaker").delete_endpoint_config(EndpointConfigName=v["config"])


def list_training(c, v):
    return c("sagemaker").list_training_jobs()


def list_notebooks(c, v):
    return c("sagemaker").list_notebook_instances()


def create_group(c, v):
    return c("sagemaker").create_model_package_group(ModelPackageGroupName=v["group"], ModelPackageGroupDescription="Churn models")


def list_groups(c, v):
    return c("sagemaker").list_model_package_groups()


def scn_deploy(c, v, s):
    sm, s3 = c("sagemaker"), c("s3")
    s.run("S3: create bucket + upload placeholder model.tar.gz", lambda: (s3.create_bucket(Bucket="ml-artifacts"),
          s3.put_object(Bucket="ml-artifacts", Key="churn/model.tar.gz", Body=b"placeholder-model-artifact")), soft=True)
    s.run("Create model", lambda: sm.create_model(ModelName=v["model"], ExecutionRoleArn=ROLE, PrimaryContainer={"Image": IMAGE, "ModelDataUrl": "s3://ml-artifacts/churn/model.tar.gz"}))
    s.run("Create endpoint config", lambda: sm.create_endpoint_config(EndpointConfigName=v["model"] + "-cfg", ProductionVariants=[
        {"VariantName": "AllTraffic", "ModelName": v["model"], "InstanceType": "ml.m5.large", "InitialInstanceCount": 1}]))
    s.run("Create endpoint", lambda: sm.create_endpoint(EndpointName=v["model"] + "-ep", EndpointConfigName=v["model"] + "-cfg"))
    s.run("Wait for endpoint InService", lambda: sm.get_waiter("endpoint_in_service").wait(EndpointName=v["model"] + "-ep", WaiterConfig={"Delay": 1, "MaxAttempts": 40}) or "InService", soft=True)
    s.run("Describe endpoint", lambda: sm.describe_endpoint(EndpointName=v["model"] + "-ep"), soft=True)
    s.run("Invoke endpoint (CSV features)", lambda: c("sagemaker-runtime").invoke_endpoint(EndpointName=v["model"] + "-ep", ContentType="text/csv", Body=v["features"].encode())["Body"].read().decode(), soft=True)
    s.run("Create model package group (registry)", lambda: sm.create_model_package_group(ModelPackageGroupName=v["model"] + "-group"), soft=True)
    s.run("List endpoints", lambda: [e["EndpointName"] for e in sm.list_endpoints()["Endpoints"]], soft=True)
    if v.flag("cleanup"):
        s.run("Delete endpoint, config, model", lambda: (sm.delete_endpoint(EndpointName=v["model"] + "-ep"), sm.delete_endpoint_config(EndpointConfigName=v["model"] + "-cfg"), sm.delete_model(ModelName=v["model"])), soft=True)


SERVICE = service(
    "sagemaker", "SageMaker", "genai", "sagemaker", "ML platform: models, endpoint configs, endpoints, model registry (+ sagemaker-runtime invoke).",
    ("sagemaker", "list_models", {}),
    [
        A("create_model", "Create model", "", [M, F("role", "Execution role ARN", ROLE), F("image", "Container image", IMAGE), F("data", "Model data (S3)", "s3://ml-artifacts/churn/model.tar.gz")], create_model),
        A("list_models", "List models", "", [], list_models),
        A("describe_model", "Describe model", "", [M], describe_model),
        A("create_config", "Create endpoint config", "", [CFG, M, F("itype", "Instance type", "ml.m5.large", "select", ["ml.t2.medium", "ml.m5.large", "ml.m5.xlarge", "ml.g5.xlarge"]), F("count", "Instance count", 1, "number")], create_config),
        A("create_endpoint", "Create endpoint", "", [EP, CFG], create_endpoint),
        A("describe_endpoint", "Describe endpoint", "", [EP], describe_endpoint),
        A("list_endpoints", "List endpoints", "", [], list_endpoints),
        A("invoke", "Invoke endpoint", "sagemaker-runtime InvokeEndpoint.", [EP, F("ctype", "Content type", "text/csv", "select", ["text/csv", "application/json"]), F("body", "Body", "42,3,129.5,0,1", "textarea", rows=2)], invoke),
        A("list_training", "List training jobs", "", [], list_training),
        A("list_notebooks", "List notebook instances", "", [], list_notebooks),
        A("create_group", "Create model package group", "", [F("group", "Group name", "churn-models")], create_group),
        A("list_groups", "List model package groups", "", [], list_groups),
        A("delete_endpoint", "Delete endpoint", "", [EP], delete_endpoint),
        A("delete_config", "Delete endpoint config", "", [CFG], delete_config),
        A("delete_model", "Delete model", "", [M], delete_model),
    ],
    [S("deploy", "Model deployment lifecycle", "Create model -> endpoint config -> endpoint, invoke it, register a model package group, then clean up.",
       [F("model", "Model name", "scenario-churn"), F("features", "Features (CSV row)", "42,3,129.5,0,1"), F("cleanup", "Clean up afterwards", True, "checkbox")], scn_deploy)],
    "https://docs.aws.amazon.com/sagemaker/latest/APIReference/Welcome.html")
