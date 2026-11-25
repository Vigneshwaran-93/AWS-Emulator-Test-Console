from collections import Counter

from ..common import F, action as A, scenario as S, service, sample_image

IMG = F("image", "Document image (PNG/JPG)", type="file", sample="invoice", help="Leave empty to use a generated sample invoice")


def _summ(r):
    blocks = r.get("Blocks", [])
    return {"block_types": dict(Counter(b["BlockType"] for b in blocks)),
            "lines": [b["Text"] for b in blocks if b["BlockType"] == "LINE"],
            "pages": r.get("DocumentMetadata", {}).get("Pages")}


def detect(c, v):
    return _summ(c("textract").detect_document_text(Document={"Bytes": v["image"]}))


def analyze(c, v):
    feats = [f.strip() for f in v["features"].split(",") if f.strip()]
    r = c("textract").analyze_document(Document={"Bytes": v["image"]}, FeatureTypes=feats)
    out = _summ(r)
    out["key_values"] = [b.get("Id") for b in r.get("Blocks", []) if b["BlockType"] == "KEY_VALUE_SET"][:20]
    return out


def expense(c, v):
    r = c("textract").analyze_expense(Document={"Bytes": v["image"]})
    docs = r.get("ExpenseDocuments", [])
    return {"documents": len(docs), "summary_fields": [{"type": f.get("Type", {}).get("Text"), "value": f.get("ValueDetection", {}).get("Text")}
                                                       for d in docs for f in d.get("SummaryFields", [])]}


def analyze_id(c, v):
    return c("textract").analyze_id(DocumentPages=[{"Bytes": v["image"]}])


def upload_and_start(c, v):
    c("s3").create_bucket(Bucket=v["bucket"]) if v.flag("create_bucket") else None
    c("s3").put_object(Bucket=v["bucket"], Key=v["key"], Body=v["image"], ContentType="image/png")
    return c("textract").start_document_text_detection(DocumentLocation={"S3Object": {"Bucket": v["bucket"], "Name": v["key"]}})


def get_job(c, v):
    r = c("textract").get_document_text_detection(JobId=v["job_id"])
    return {"JobStatus": r.get("JobStatus"), **_summ(r)}


def scn_invoice(c, v, s):
    tx, s3 = c("textract"), c("s3")
    img = v["image"]
    s.run("Create bucket", lambda: s3.create_bucket(Bucket=v["bucket"]), soft=True)
    s.run("Upload invoice image to S3", lambda: s3.put_object(Bucket=v["bucket"], Key="inbox/invoice-1042.png", Body=img, ContentType="image/png"), soft=True)
    s.run("Detect text (OCR)", lambda: _summ(tx.detect_document_text(Document={"Bytes": img})))
    s.run("Detect text straight from S3", lambda: _summ(tx.detect_document_text(Document={"S3Object": {"Bucket": v["bucket"], "Name": "inbox/invoice-1042.png"}})), soft=True)
    s.run("Analyze forms + tables", lambda: _summ(tx.analyze_document(Document={"Bytes": img}, FeatureTypes=["FORMS", "TABLES"])), soft=True)
    s.run("Analyze expense (invoice fields)", lambda: expense(c, {"image": img}), soft=True)
    if v.flag("cleanup"):
        s.run("Delete S3 object + bucket", lambda: (s3.delete_object(Bucket=v["bucket"], Key="inbox/invoice-1042.png"), s3.delete_bucket(Bucket=v["bucket"])), soft=True)


SERVICE = service(
    "textract", "Textract", "genai", "textract", "Document AI: OCR, forms/tables, invoices and ID analysis.",
    ("textract", "detect_document_text", {"Document": {"Bytes": sample_image("invoice")}}),
    [
        A("detect", "Detect text (OCR)", "Upload an image or use the generated invoice.", [IMG], detect),
        A("analyze", "Analyze document", "Forms / tables / queries layout analysis.", [IMG, F("features", "Feature types", "FORMS,TABLES")], analyze),
        A("expense", "Analyze expense", "Invoice & receipt fields.", [IMG], expense),
        A("analyze_id", "Analyze ID", "Identity documents.", [IMG], analyze_id),
        A("upload_and_start", "Async job from S3", "Uploads the image to S3 then StartDocumentTextDetection.", [IMG, F("bucket", "Bucket", "textract-inbox", sync=False), F("key", "Key", "scans/invoice.png"), F("create_bucket", "Create bucket first", True, "checkbox")], upload_and_start),
        A("get_job", "Get async job result", "", [F("job_id", "Job ID", "")], get_job),
    ],
    [S("invoice", "Invoice processing", "Upload an invoice to S3, OCR it (bytes and S3 object), analyze forms/tables and extract expense fields.",
       [IMG, F("bucket", "Bucket", "invoice-inbox"), F("cleanup", "Clean up afterwards", True, "checkbox")], scn_invoice)],
    "https://docs.aws.amazon.com/textract/latest/dg/API_Reference.html")
