from ..common import F, action as A, scenario as S, service

B = F("bucket", "Bucket name", "demo-docs-bucket", sync=True, help="Lower-case, 3-63 chars")
K = F("key", "Object key", "reports/2026/q3-summary.txt")


def create_bucket(c, v):
    return c("s3").create_bucket(Bucket=v["bucket"])


def list_buckets(c, v):
    return c("s3").list_buckets()


def put_object(c, v):
    return c("s3").put_object(Bucket=v["bucket"], Key=v["key"], Body=v["content"].encode(),
                              ContentType=v["content_type"], Metadata={"uploaded-by": v["uploader"]})


def get_object(c, v):
    r = c("s3").get_object(Bucket=v["bucket"], Key=v["key"])
    return {"ContentType": r.get("ContentType"), "ContentLength": r.get("ContentLength"),
            "Metadata": r.get("Metadata"), "ETag": r.get("ETag"), "Body": r["Body"].read().decode("utf-8", "replace")}


def head_object(c, v):
    return c("s3").head_object(Bucket=v["bucket"], Key=v["key"])


def list_objects(c, v):
    return c("s3").list_objects_v2(Bucket=v["bucket"], Prefix=v["prefix"])


def copy_object(c, v):
    return c("s3").copy_object(Bucket=v["bucket"], Key=v["dst"], CopySource={"Bucket": v["bucket"], "Key": v["key"]})


def presign(c, v):
    url = c("s3").generate_presigned_url("get_object", Params={"Bucket": v["bucket"], "Key": v["key"]},
                                         ExpiresIn=int(v.num("expires", 900)))
    return {"presigned_url": url, "note": "Generated locally by the SDK (no API call). The URL embeds the emulator port."}


def versioning(c, v):
    return c("s3").put_bucket_versioning(Bucket=v["bucket"], VersioningConfiguration={"Status": "Enabled"})


def list_versions(c, v):
    return c("s3").list_object_versions(Bucket=v["bucket"], Prefix=v["prefix"])


def tagging(c, v):
    return c("s3").put_bucket_tagging(Bucket=v["bucket"], Tagging={"TagSet": [
        {"Key": "env", "Value": v["env"]}, {"Key": "team", "Value": v["team"]}]})


def delete_object(c, v):
    return c("s3").delete_object(Bucket=v["bucket"], Key=v["key"])


def delete_bucket(c, v):
    return c("s3").delete_bucket(Bucket=v["bucket"])


def scn_archive(c, v, s):
    s3, b = c("s3"), v["bucket"]
    s.run("Create bucket", lambda: s3.create_bucket(Bucket=b))
    s.run("Enable versioning", lambda: s3.put_bucket_versioning(Bucket=b, VersioningConfiguration={"Status": "Enabled"}), soft=True)
    docs = {"contracts/acme-msa.txt": "Master Services Agreement between ACME and Globex. Term: 24 months.",
            "contracts/acme-msa-v2.txt": "MSA amendment: payment terms net-45.",
            "reports/q3.csv": "region,revenue\nus-east,120000\neu-west,98000\n"}
    for k, body in docs.items():
        s.run(f"Upload {k}", lambda k=k, body=body: s3.put_object(Bucket=b, Key=k, Body=body.encode(), ContentType="text/plain"))
    s.run("Overwrite q3.csv (creates a new version)", lambda: s3.put_object(Bucket=b, Key="reports/q3.csv", Body=b"region,revenue\nus-east,125000\n"), soft=True)
    s.run("List objects under contracts/", lambda: [o["Key"] for o in s3.list_objects_v2(Bucket=b, Prefix="contracts/").get("Contents", [])])
    s.run("Download reports/q3.csv", lambda: s3.get_object(Bucket=b, Key="reports/q3.csv")["Body"].read())
    s.run("List versions of reports/q3.csv", lambda: [(x["VersionId"], x["IsLatest"]) for x in s3.list_object_versions(Bucket=b, Prefix="reports/q3.csv").get("Versions", [])], soft=True)
    s.run("Presign download URL", lambda: s3.generate_presigned_url("get_object", Params={"Bucket": b, "Key": "contracts/acme-msa.txt"}, ExpiresIn=300))
    if v.flag("cleanup"):
        def wipe():
            for ver in s3.list_object_versions(Bucket=b).get("Versions", []):
                s3.delete_object(Bucket=b, Key=ver["Key"], VersionId=ver["VersionId"])
            for o in s3.list_objects_v2(Bucket=b).get("Contents", []):
                s3.delete_object(Bucket=b, Key=o["Key"])
        s.run("Delete all objects", wipe, soft=True)
        s.run("Delete bucket", lambda: s3.delete_bucket(Bucket=b), soft=True)


SERVICE = service(
    "s3", "S3", "basic", "s3", "Object storage: buckets, objects, versioning, tagging, presigned URLs.",
    ("s3", "list_buckets", {}),
    [
        A("create_bucket", "Create bucket", "Creates a new bucket.", [B], create_bucket),
        A("list_buckets", "List buckets", "Lists all buckets in the emulator account.", [], list_buckets),
        A("put_object", "Upload object", "Stores text content as an object.", [B, K,
          F("content_type", "Content type", "text/plain", "select", ["text/plain", "application/json", "text/csv", "text/html"]),
          F("uploader", "Metadata: uploaded-by", "demo-user"),
          F("content", "Content", "Q3 summary: revenue up 12% quarter over quarter.\nTop region: us-east.", "textarea")], put_object),
        A("get_object", "Download object", "Reads the object back and shows its content.", [B, K], get_object),
        A("head_object", "Head object", "Fetches metadata only.", [B, K], head_object),
        A("list_objects", "List objects", "ListObjectsV2 with prefix filter.", [B, F("prefix", "Prefix", "reports/")], list_objects),
        A("copy_object", "Copy object", "Server-side copy inside the bucket.", [B, K, F("dst", "Destination key", "archive/q3-summary-copy.txt")], copy_object),
        A("presign", "Presigned URL", "Generate a time-limited download URL.", [B, K, F("expires", "Expires (s)", 900, "number")], presign),
        A("versioning", "Enable versioning", "PutBucketVersioning = Enabled.", [B], versioning),
        A("list_versions", "List object versions", "ListObjectVersions.", [B, F("prefix", "Prefix", "")], list_versions),
        A("tagging", "Tag bucket", "PutBucketTagging.", [B, F("env", "env tag", "dev"), F("team", "team tag", "platform")], tagging),
        A("delete_object", "Delete object", "", [B, K], delete_object),
        A("delete_bucket", "Delete bucket", "Bucket must be empty.", [B], delete_bucket),
    ],
    [S("archive", "Document archive lifecycle", "Create a versioned bucket, upload contracts and reports, overwrite a file, list versions, presign a URL, then optionally clean up.",
       [B, F("cleanup", "Clean up afterwards", True, "checkbox")], scn_archive)],
    "https://docs.aws.amazon.com/AmazonS3/latest/API/Welcome.html")
