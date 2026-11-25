import json
from decimal import Decimal

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer

from ..common import F, action as A, scenario as S, service, wait_table

_ser, _de = TypeSerializer(), TypeDeserializer()


def ser(o):
    return {k: _ser.serialize(v) for k, v in o.items()}


def de(o):
    return {k: _de.deserialize(v) for k, v in o.items()}


def pj(s):
    return json.loads(s, parse_float=Decimal)


T = F("table", "Table", "orders", sync=True)
PK = F("pk_name", "Partition key", "customerId", sync=True)
SK = F("sk_name", "Sort key (optional)", "orderId", sync=True)
ITEM = ('{\n  "customerId": "C-1001",\n  "orderId": "O-2026-0001",\n  "status": "PLACED",\n'
        '  "total": 249.99,\n  "items": [{"sku": "KB-77", "qty": 1}, {"sku": "MS-12", "qty": 2}]\n}')


def create_table(c, v):
    ks = [{"AttributeName": v["pk_name"], "KeyType": "HASH"}]
    ad = [{"AttributeName": v["pk_name"], "AttributeType": v["pk_type"]}]
    if v["sk_name"]:
        ks.append({"AttributeName": v["sk_name"], "KeyType": "RANGE"})
        ad.append({"AttributeName": v["sk_name"], "AttributeType": v["sk_type"]})
    return c("dynamodb").create_table(TableName=v["table"], KeySchema=ks, AttributeDefinitions=ad, BillingMode="PAY_PER_REQUEST")


def put_item(c, v):
    return c("dynamodb").put_item(TableName=v["table"], Item=ser(pj(v["item"])), ReturnConsumedCapacity="TOTAL")


def get_item(c, v):
    r = c("dynamodb").get_item(TableName=v["table"], Key=ser(pj(v["key"])))
    return {"Item": de(r["Item"]) if "Item" in r else None}


def query(c, v):
    names, vals = {"#p": v["pk_name"]}, {":p": _ser.serialize(v["pk_value"])}
    expr = "#p = :p"
    if v["sk_prefix"]:
        names["#s"] = v["sk_name"]
        vals[":s"] = _ser.serialize(v["sk_prefix"])
        expr += " AND begins_with(#s, :s)"
    r = c("dynamodb").query(TableName=v["table"], KeyConditionExpression=expr, ExpressionAttributeNames=names,
                            ExpressionAttributeValues=vals)
    return {"Count": r["Count"], "Items": [de(i) for i in r["Items"]]}


def scan(c, v):
    kw = {"TableName": v["table"]}
    if v["attr"]:
        kw.update(FilterExpression="#a = :v", ExpressionAttributeNames={"#a": v["attr"]},
                  ExpressionAttributeValues={":v": _ser.serialize(v["value"])})
    if v.num("limit"):
        kw["Limit"] = int(v.num("limit"))
    r = c("dynamodb").scan(**kw)
    return {"Count": r["Count"], "ScannedCount": r["ScannedCount"], "Items": [de(i) for i in r["Items"]]}


def update_item(c, v):
    return c("dynamodb").update_item(TableName=v["table"], Key=ser(pj(v["key"])), UpdateExpression="SET #a = :v",
                                     ExpressionAttributeNames={"#a": v["attr"]}, ExpressionAttributeValues={":v": _ser.serialize(v["value"])},
                                     ReturnValues="ALL_NEW")


def delete_item(c, v):
    return c("dynamodb").delete_item(TableName=v["table"], Key=ser(pj(v["key"])))


def batch_write(c, v):
    items = pj(v["items"])
    return c("dynamodb").batch_write_item(RequestItems={v["table"]: [{"PutRequest": {"Item": ser(i)}} for i in items]})


def partiql(c, v):
    r = c("dynamodb").execute_statement(Statement=v["statement"])
    return {"Items": [de(i) for i in r.get("Items", [])]}


def list_tables(c, v):
    return c("dynamodb").list_tables()


def describe(c, v):
    return c("dynamodb").describe_table(TableName=v["table"])


def delete_table(c, v):
    return c("dynamodb").delete_table(TableName=v["table"])


def scn_orders(c, v, s):
    d, t = c("dynamodb"), v["table"]
    s.run("Create table (customerId + orderId)", lambda: d.create_table(
        TableName=t, KeySchema=[{"AttributeName": "customerId", "KeyType": "HASH"}, {"AttributeName": "orderId", "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": "customerId", "AttributeType": "S"}, {"AttributeName": "orderId", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST"))
    s.run("Wait for table to become ACTIVE", lambda: wait_table(c, t))
    orders = [("C-1001", "O-1", "PLACED", 249.99), ("C-1001", "O-2", "PLACED", 19.5), ("C-1002", "O-3", "SHIPPED", 89.0), ("C-1003", "O-4", "PLACED", 540.0)]
    for cid, oid, st, tot in orders:
        s.run(f"Put order {oid} for {cid}", lambda cid=cid, oid=oid, st=st, tot=tot: d.put_item(
            TableName=t, Item=ser({"customerId": cid, "orderId": oid, "status": st, "total": Decimal(str(tot))})))
    s.run("Query orders of C-1001", lambda: [de(i) for i in d.query(
        TableName=t, KeyConditionExpression="customerId = :c", ExpressionAttributeValues={":c": {"S": "C-1001"}})["Items"]])
    s.run("Mark O-1 as SHIPPED", lambda: de(d.update_item(
        TableName=t, Key=ser({"customerId": "C-1001", "orderId": "O-1"}), UpdateExpression="SET #s = :s", ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": {"S": "SHIPPED"}}, ReturnValues="ALL_NEW")["Attributes"]))
    s.run("Scan for status = PLACED", lambda: [de(i) for i in d.scan(
        TableName=t, FilterExpression="#s = :s", ExpressionAttributeNames={"#s": "status"}, ExpressionAttributeValues={":s": {"S": "PLACED"}})["Items"]])
    s.run("PartiQL: total > 100", lambda: [de(i) for i in d.execute_statement(Statement=f'SELECT * FROM "{t}" WHERE total > 100')["Items"]], soft=True)
    if v.flag("cleanup"):
        s.run("Delete table", lambda: d.delete_table(TableName=t), soft=True)


SERVICE = service(
    "dynamodb", "DynamoDB", "basic", "dynamodb", "NoSQL key-value tables: items, queries, scans, PartiQL.",
    ("dynamodb", "list_tables", {}),
    [
        A("create_table", "Create table", "On-demand (PAY_PER_REQUEST) table.", [T, PK, F("pk_type", "PK type", "S", "select", ["S", "N", "B"]), SK, F("sk_type", "SK type", "S", "select", ["S", "N", "B"])], create_table),
        A("list_tables", "List tables", "", [], list_tables),
        A("describe", "Describe table", "", [T], describe),
        A("put_item", "Put item", "Plain JSON is converted to DynamoDB attribute types for you.", [T, F("item", "Item (JSON)", ITEM, "textarea", rows=9)], put_item),
        A("get_item", "Get item", "", [T, F("key", "Key (JSON)", '{"customerId": "C-1001", "orderId": "O-2026-0001"}', "textarea", rows=3)], get_item),
        A("query", "Query", "Partition key (+ optional sort key prefix).", [T, PK, SK, F("pk_value", "Partition value", "C-1001"), F("sk_prefix", "Sort key begins with", "O-")], query),
        A("scan", "Scan with filter", "Leave attribute empty for a full scan.", [T, F("attr", "Filter attribute", "status"), F("value", "Equals", "PLACED"), F("limit", "Limit", "", "number")], scan),
        A("update_item", "Update attribute", "SET one attribute.", [T, F("key", "Key (JSON)", '{"customerId": "C-1001", "orderId": "O-2026-0001"}', "textarea", rows=3), F("attr", "Attribute", "status"), F("value", "New value", "SHIPPED")], update_item),
        A("batch_write", "Batch write", "BatchWriteItem with a JSON array.", [T, F("items", "Items (JSON array)", '[{"customerId":"C-2001","orderId":"O-10","status":"PLACED"},{"customerId":"C-2002","orderId":"O-11","status":"PLACED"}]', "textarea", rows=5)], batch_write),
        A("partiql", "PartiQL statement", "ExecuteStatement.", [F("statement", "Statement", 'SELECT * FROM "orders" WHERE customerId = \'C-1001\'', "textarea", rows=3)], partiql),
        A("delete_item", "Delete item", "", [T, F("key", "Key (JSON)", '{"customerId": "C-1001", "orderId": "O-2026-0001"}', "textarea", rows=3)], delete_item),
        A("delete_table", "Delete table", "", [T], delete_table),
    ],
    [S("orders", "E-commerce order book", "Create an orders table, insert 4 orders, query by customer, update a status, filter-scan, run a PartiQL query.",
       [F("table", "Table", "orders-demo"), F("cleanup", "Clean up afterwards", True, "checkbox")], scn_orders)],
    "https://docs.aws.amazon.com/amazondynamodb/latest/APIReference/Welcome.html")
