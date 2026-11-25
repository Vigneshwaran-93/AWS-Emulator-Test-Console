"""Cross-service end-to-end scenarios."""
import base64
import json
from decimal import Decimal

from .common import F, scenario as S, make_zip, wait_table, wait_lambda
from .services.dynamodb import de, ser


def _text(r):
    try:
        return "".join(b.get("text", "") for b in r["output"]["message"]["content"])
    except Exception:  # noqa
        return ""


# ---------------------------------------------------------------------------------------------
def order_pipeline(c, v, s):
    s3, ddb, sqs = c("s3"), c("dynamodb"), c("sqs")
    b, t, qn = v["prefix"] + "-orders", v["prefix"] + "-orders", v["prefix"] + "-order-queue"
    orders = [{"customerId": "C-1001", "orderId": "O-1", "sku": "KB-77", "qty": 1, "total": 79.0},
              {"customerId": "C-1002", "orderId": "O-2", "sku": "MS-12", "qty": 3, "total": 45.0},
              {"customerId": "C-1001", "orderId": "O-3", "sku": "HD-90", "qty": 2, "total": 260.0}]
    s.run("S3: create inbox bucket", lambda: s3.create_bucket(Bucket=b))
    s.run("DynamoDB: create orders table", lambda: ddb.create_table(
        TableName=t, KeySchema=[{"AttributeName": "customerId", "KeyType": "HASH"}, {"AttributeName": "orderId", "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": "customerId", "AttributeType": "S"}, {"AttributeName": "orderId", "AttributeType": "S"}], BillingMode="PAY_PER_REQUEST"))
    s.run("DynamoDB: wait for ACTIVE", lambda: wait_table(c, t))
    q = s.run("SQS: create queue", lambda: sqs.create_queue(QueueName=qn)["QueueUrl"])
    for o in orders:
        s.run(f"S3: upload order {o['orderId']}.json", lambda o=o: s3.put_object(Bucket=b, Key=f"inbox/{o['orderId']}.json", Body=json.dumps(o).encode(), ContentType="application/json"))
        s.run(f"SQS: enqueue {o['orderId']}", lambda o=o: sqs.send_message(QueueUrl=q, MessageBody=json.dumps({"bucket": b, "key": f"inbox/{o['orderId']}.json"})))
    processed = 0
    for _ in range(len(orders)):
        msgs = s.run("SQS: poll for a message", lambda: sqs.receive_message(QueueUrl=q, MaxNumberOfMessages=1, WaitTimeSeconds=1).get("Messages", []), show=False)
        if not msgs:
            break
        m = msgs[0]
        ref = json.loads(m["Body"])
        order = s.run(f"S3: fetch {ref['key']}", lambda ref=ref: json.loads(s3.get_object(Bucket=ref["bucket"], Key=ref["key"])["Body"].read(), parse_float=Decimal), show=False)
        s.run(f"DynamoDB: store order {order['orderId']}", lambda order=order: ddb.put_item(TableName=t, Item=ser({**order, "status": "PROCESSED"})))
        s.run("SQS: delete processed message", lambda m=m: sqs.delete_message(QueueUrl=q, ReceiptHandle=m["ReceiptHandle"]), show=False)
        processed += 1
    s.note("Orders processed", processed)
    s.run("DynamoDB: query C-1001 orders", lambda: [de(i) for i in ddb.query(TableName=t, KeyConditionExpression="customerId = :c", ExpressionAttributeValues={":c": {"S": "C-1001"}})["Items"]])
    if v.flag("cleanup"):
        def wipe():
            for o in s3.list_objects_v2(Bucket=b).get("Contents", []):
                s3.delete_object(Bucket=b, Key=o["Key"])
            s3.delete_bucket(Bucket=b)
            ddb.delete_table(TableName=t)
            sqs.delete_queue(QueueUrl=q)
        s.run("Cleanup bucket, table, queue", wipe, soft=True)


# ---------------------------------------------------------------------------------------------
def doc_intel(c, v, s):
    s3, tx, cp, tr, brt, ddb, polly = c("s3"), c("textract"), c("comprehend"), c("translate"), c("bedrock-runtime"), c("dynamodb"), c("polly")
    b, t = v["prefix"] + "-docs", v["prefix"] + "-doc-insights"
    img = v["image"]
    s.run("S3: create bucket", lambda: s3.create_bucket(Bucket=b))
    s.run("S3: upload scanned invoice", lambda: s3.put_object(Bucket=b, Key="scans/invoice.png", Body=img, ContentType="image/png"))
    blocks = s.run("Textract: OCR the invoice", lambda: tx.detect_document_text(Document={"Bytes": img}), show=False)
    lines = [x["Text"] for x in (blocks or {}).get("Blocks", []) if x["BlockType"] == "LINE"]
    s.note("Extracted lines", lines)
    text = "\n".join(lines) or "Invoice INV-2026-1042 for Jane Doe, total $128.50, contact jane.doe@example.com"
    s.run("Comprehend: entities", lambda: [(e["Type"], e["Text"]) for e in cp.detect_entities(Text=text, LanguageCode="en")["Entities"]], soft=True)
    s.run("Comprehend: PII", lambda: [(p["Type"], p["Score"]) for p in cp.detect_pii_entities(Text=text, LanguageCode="en")["Entities"]], soft=True)
    summ = s.run("Bedrock: summarize the invoice", lambda: _text(brt.converse(
        modelId=v["model"], system=[{"text": "Summarize this invoice in two sentences for an accounts-payable clerk."}],
        messages=[{"role": "user", "content": [{"text": text}]}], inferenceConfig={"maxTokens": 200, "temperature": 0.2})), soft=True) or text[:200]
    es = s.run("Translate: summary -> Spanish", lambda: tr.translate_text(Text=summ, SourceLanguageCode="en", TargetLanguageCode="es")["TranslatedText"], soft=True)
    s.run("DynamoDB: create insights table", lambda: ddb.create_table(TableName=t, KeySchema=[{"AttributeName": "doc", "KeyType": "HASH"}],
                                                                       AttributeDefinitions=[{"AttributeName": "doc", "AttributeType": "S"}], BillingMode="PAY_PER_REQUEST"))
    s.run("DynamoDB: wait for ACTIVE", lambda: wait_table(c, t))
    s.run("DynamoDB: store insights", lambda: ddb.put_item(TableName=t, Item=ser({"doc": "scans/invoice.png", "lines": len(lines), "summary_en": summ, "summary_es": es or ""})))
    s.run("Polly: narrate the summary", lambda: {"audio_bytes": len(polly.synthesize_speech(Text=summ[:300], VoiceId="Joanna", OutputFormat="mp3", Engine="neural")["AudioStream"].read())}, soft=True)
    if v.flag("cleanup"):
        s.run("Cleanup", lambda: (s3.delete_object(Bucket=b, Key="scans/invoice.png"), s3.delete_bucket(Bucket=b), ddb.delete_table(TableName=t)), soft=True)


# ---------------------------------------------------------------------------------------------
def secure_genai(c, v, s):
    iam, sm, lam, br = c("iam"), c("secretsmanager"), c("lambda"), c("bedrock")
    p = v["prefix"]
    trust = json.dumps({"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]})
    pol = json.dumps({"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": ["bedrock:InvokeModel", "bedrock:Converse"], "Resource": "*"},
        {"Effect": "Allow", "Action": "secretsmanager:GetSecretValue", "Resource": "*"}]})
    role = s.run("IAM: create function role", lambda: iam.create_role(RoleName=p + "-role", AssumeRolePolicyDocument=trust)["Role"]["Arn"])
    parn = s.run("IAM: create least-privilege policy", lambda: iam.create_policy(PolicyName=p + "-policy", PolicyDocument=pol)["Policy"]["Arn"], soft=True)
    if parn:
        s.run("IAM: attach policy to role", lambda: iam.attach_role_policy(RoleName=p + "-role", PolicyArn=parn), soft=True)
    s.run("Secrets Manager: store model API config", lambda: sm.create_secret(Name=p + "/llm-config", SecretString=json.dumps({"model": v["model"], "max_tokens": 512})))
    code = ("import json\n\ndef handler(event, context):\n    return {'answer': 'echo: ' + event.get('question', ''), 'model': 'stub'}\n")
    s.run("Lambda: deploy chat handler", lambda: lam.create_function(FunctionName=p + "-chat", Runtime="python3.12", Role=role, Handler="lambda_function.handler",
                                                                      Code={"ZipFile": make_zip("lambda_function.py", code)}))
    s.run("Lambda: wait for Active", lambda: wait_lambda(c, p + "-chat"), soft=True)
    s.run("Lambda: invoke", lambda: json.loads(lam.invoke(FunctionName=p + "-chat", Payload=json.dumps({"question": "What is my balance?"}).encode())["Payload"].read()), soft=True)
    gid = s.run("Bedrock: create guardrail", lambda: br.create_guardrail(
        name=p + "-guardrail", topicPolicyConfig={"topicsConfig": [{"name": "Medical", "definition": "Diagnosis or treatment advice.", "examples": ["What medicine should I take?"], "type": "DENY"}]},
        blockedInputMessaging="Blocked.", blockedOutputsMessaging="Blocked."), soft=True)
    if gid:
        s.run("Bedrock Runtime: test guardrail on risky input", lambda: c("bedrock-runtime").apply_guardrail(
            guardrailIdentifier=gid["guardrailId"], guardrailVersion="DRAFT", source="INPUT", content=[{"text": {"text": "What medicine should I take for chest pain?"}}]), soft=True)
    if v.flag("cleanup"):
        s.run("Cleanup", lambda: [lam.delete_function(FunctionName=p + "-chat"), sm.delete_secret(SecretId=p + "/llm-config", ForceDeleteWithoutRecovery=True),
                                  *( [iam.detach_role_policy(RoleName=p + "-role", PolicyArn=parn)] if parn else []),
                                  iam.delete_role(RoleName=p + "-role"), *([iam.delete_policy(PolicyArn=parn)] if parn else []),
                                  *([br.delete_guardrail(guardrailIdentifier=gid["guardrailId"])] if gid else [])], soft=True)


MODEL = F("model", "Bedrock model", "anthropic.claude-haiku-4-5-20251001-v1:0")
CLEAN = F("cleanup", "Clean up afterwards", True, "checkbox")

WORKFLOWS = [
    S("order_pipeline", "Order pipeline: S3 -> SQS -> DynamoDB", "Orders land in S3, are announced on a queue, consumed, stored in DynamoDB and queried. Exercises 3 core services together.",
      [F("prefix", "Resource prefix", "shop"), CLEAN], order_pipeline),
    S("doc_intel", "Document intelligence (GenAI)", "Scanned invoice -> S3 -> Textract OCR -> Comprehend -> Bedrock summary -> Translate -> DynamoDB -> Polly audio.",
      [F("prefix", "Resource prefix", "docint"), F("image", "Invoice image (optional)", type="file", sample="invoice"), MODEL, CLEAN], doc_intel),
    S("secure_genai", "Secure GenAI app bootstrap", "IAM role + policy, Secrets Manager config, Lambda function, Bedrock guardrail and guardrail test.",
      [F("prefix", "Resource prefix", "genai-app"), MODEL, CLEAN], secure_genai),
]
for w in WORKFLOWS:
    w["svc"] = "workflows"
    w["svc_title"] = "Workflow"
