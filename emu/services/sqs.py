import json

from ..common import F, action as A, scenario as S, service

Q = F("queue", "Queue name", "order-events", sync=True)


def url(c, name):
    return c("sqs").get_queue_url(QueueName=name)["QueueUrl"]


def create_queue(c, v):
    attrs = {"VisibilityTimeout": str(int(v.num("visibility", 30))), "MessageRetentionPeriod": "86400"}
    name = v["queue"]
    if v.flag("fifo"):
        if not name.endswith(".fifo"):
            name += ".fifo"
        attrs.update(FifoQueue="true", ContentBasedDeduplication="true")
    return c("sqs").create_queue(QueueName=name, Attributes=attrs)


def list_queues(c, v):
    return c("sqs").list_queues(QueueNamePrefix=v["prefix"])


def send(c, v):
    kw = dict(QueueUrl=url(c, v["queue"]), MessageBody=v["body"],
              MessageAttributes={"source": {"DataType": "String", "StringValue": v["source"]}})
    if v["queue"].endswith(".fifo"):
        kw["MessageGroupId"] = v["group"] or "g1"
    elif v.num("delay"):
        kw["DelaySeconds"] = int(v.num("delay"))
    return c("sqs").send_message(**kw)


def send_batch(c, v):
    msgs = v.lines("bodies")
    return c("sqs").send_message_batch(QueueUrl=url(c, v["queue"]), Entries=[{"Id": str(i), "MessageBody": m} for i, m in enumerate(msgs)])


def receive(c, v):
    r = c("sqs").receive_message(QueueUrl=url(c, v["queue"]), MaxNumberOfMessages=int(v.num("max", 5)),
                                 WaitTimeSeconds=int(v.num("wait", 0)), MessageAttributeNames=["All"], AttributeNames=["All"])
    return {"count": len(r.get("Messages", [])), "Messages": r.get("Messages", [])}


def delete_msg(c, v):
    return c("sqs").delete_message(QueueUrl=url(c, v["queue"]), ReceiptHandle=v["receipt"])


def attrs(c, v):
    return c("sqs").get_queue_attributes(QueueUrl=url(c, v["queue"]), AttributeNames=["All"])


def purge(c, v):
    return c("sqs").purge_queue(QueueUrl=url(c, v["queue"]))


def delete_queue(c, v):
    return c("sqs").delete_queue(QueueUrl=url(c, v["queue"]))


def scn_dlq(c, v, s):
    q, name = c("sqs"), v["queue"]
    dlq = s.run("Create dead-letter queue", lambda: q.create_queue(QueueName=name + "-dlq")["QueueUrl"])
    dlq_arn = s.run("Get DLQ ARN", lambda: q.get_queue_attributes(QueueUrl=dlq, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"])
    main = s.run("Create main queue with redrive policy (maxReceiveCount=2)", lambda: q.create_queue(
        QueueName=name, Attributes={"VisibilityTimeout": "1", "RedrivePolicy": json.dumps({"deadLetterTargetArn": dlq_arn, "maxReceiveCount": 2})})["QueueUrl"])
    for i in range(1, 4):
        s.run(f"Send job {i}", lambda i=i: q.send_message(QueueUrl=main, MessageBody=json.dumps({"job": i, "task": "resize-image", "file": f"img{i}.png"})))
    got = s.run("Receive up to 3 jobs", lambda: q.receive_message(QueueUrl=main, MaxNumberOfMessages=3, WaitTimeSeconds=1).get("Messages", []))
    if got:
        s.run("Acknowledge (delete) first job", lambda: q.delete_message(QueueUrl=main, ReceiptHandle=got[0]["ReceiptHandle"]))
    s.run("Queue depth", lambda: {k: v2 for k, v2 in q.get_queue_attributes(QueueUrl=main, AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"])["Attributes"].items()})
    if v.flag("cleanup"):
        s.run("Delete queues", lambda: [q.delete_queue(QueueUrl=main), q.delete_queue(QueueUrl=dlq)], soft=True)


SERVICE = service(
    "sqs", "SQS", "basic", "sqs", "Message queues: standard & FIFO, batching, visibility timeout, DLQ.",
    ("sqs", "list_queues", {}),
    [
        A("create_queue", "Create queue", "Standard or FIFO queue.", [Q, F("fifo", "FIFO queue", False, "checkbox"), F("visibility", "Visibility timeout (s)", 30, "number")], create_queue),
        A("list_queues", "List queues", "", [F("prefix", "Name prefix", "")], list_queues),
        A("send", "Send message", "", [Q, F("body", "Message body", '{"event": "order.created", "orderId": "O-2026-0001", "amount": 249.99}', "textarea"), F("source", "Attribute 'source'", "checkout-service"), F("delay", "Delay (s)", 0, "number"), F("group", "FIFO group id", "g1")], send),
        A("send_batch", "Send batch", "One message per line (max 10).", [Q, F("bodies", "Messages (one per line)", "order O-1 created\norder O-2 created\norder O-3 created", "textarea")], send_batch),
        A("receive", "Receive messages", "", [Q, F("max", "Max messages", 5, "number"), F("wait", "Long-poll wait (s)", 0, "number")], receive),
        A("delete_msg", "Delete message", "Paste a ReceiptHandle from the receive result.", [Q, F("receipt", "Receipt handle", "")], delete_msg),
        A("attrs", "Queue attributes", "", [Q], attrs),
        A("purge", "Purge queue", "", [Q], purge),
        A("delete_queue", "Delete queue", "", [Q], delete_queue),
    ],
    [S("dlq", "Job queue with dead-letter queue", "Create DLQ + main queue with a redrive policy, send jobs, receive, acknowledge and inspect depth.",
       [F("queue", "Queue name", "image-jobs"), F("cleanup", "Clean up afterwards", True, "checkbox")], scn_dlq)],
    "https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/Welcome.html")
